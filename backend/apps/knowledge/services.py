from __future__ import annotations

import hashlib
import logging
import uuid
from dataclasses import dataclass
from typing import Any

from django.db import transaction
from django.utils import timezone
from pgvector.django import CosineDistance

from apps.accounts.models import User
from apps.billing import usage
from apps.billing.models import Metric
from apps.knowledge import processing
from apps.knowledge.embeddings import EmbeddingError, get_embedder
from apps.knowledge.models import KnowledgeChunk, KnowledgeSource, SourceKind, SourceStatus
from apps.workspaces.models import Workspace
from common.files import ValidatedUpload
from common.safe_http import UnsafeURLError, safe_request

logger = logging.getLogger(__name__)

DEFAULT_TOP_K = 5
MAX_TOP_K = 20


# ---------------------------------------------------------------------------
# Source lifecycle
# ---------------------------------------------------------------------------
@transaction.atomic
def create_source(
    *,
    workspace: Workspace,
    kind: str,
    title: str,
    created_by: User | None,
    upload: ValidatedUpload | None = None,
    url: str = "",
    faq: list[dict[str, str]] | None = None,
    text: str = "",
    metadata: dict[str, Any] | None = None,
) -> KnowledgeSource:
    size = upload.size if upload else len(text) + sum(len(i["question"]) + len(i["answer"]) for i in faq or [])
    usage.check_knowledge_capacity(workspace.organization, size)
    source = KnowledgeSource(
        workspace=workspace,
        kind=kind,
        title=title.strip()[:200],
        url=url,
        faq=faq or [],
        text=text,
        metadata=metadata or {},
        created_by=created_by,
    )
    if upload:
        source.file = upload.file
        source.filename = upload.filename
        source.content_type = upload.content_type
        source.size = upload.size
    source.save()
    schedule_ingestion(source)
    return source


def schedule_ingestion(source: KnowledgeSource) -> None:
    from apps.knowledge.tasks import ingest_source_task

    source_id = str(source.id)
    transaction.on_commit(lambda: ingest_source_task.delay(source_id))


def request_reindex(source: KnowledgeSource) -> KnowledgeSource:
    KnowledgeSource.objects.filter(pk=source.pk).update(status=SourceStatus.PENDING, error="")
    source.refresh_from_db()
    schedule_ingestion(source)
    return source


def delete_source(source: KnowledgeSource) -> None:
    file = source.file
    source.delete()  # chunks cascade
    if file:
        transaction.on_commit(lambda: file.storage.delete(file.name))


# ---------------------------------------------------------------------------
# Ingestion (runs in Celery)
# ---------------------------------------------------------------------------
def _extract(source: KnowledgeSource) -> list[processing.Section]:
    if source.kind == SourceKind.FILE:
        with source.file.open("rb") as fh:
            data = fh.read()
        if source.content_type == "application/pdf":
            return processing.extract_pdf(data)
        return processing.extract_text_file(data)
    if source.kind == SourceKind.URL:
        try:
            response = safe_request("GET", source.url, timeout=15, max_bytes=3 * 1024 * 1024)
        except UnsafeURLError as exc:
            raise processing.ExtractionError(str(exc)) from exc
        except Exception as exc:
            raise processing.ExtractionError("The page could not be fetched.") from exc
        if response.status_code >= 400:
            raise processing.ExtractionError(f"The page returned HTTP {response.status_code}.")
        if response.content_type in ("text/html", "application/xhtml+xml"):
            title, sections = processing.extract_html(response.body, response.url)
            if title and source.title == source.url:
                KnowledgeSource.objects.filter(pk=source.pk).update(title=title)
            return sections
        if response.content_type.startswith("text/"):
            return processing.extract_text_file(response.body)
        raise processing.ExtractionError(f"Unsupported content type: {response.content_type or 'unknown'}.")
    if source.kind == SourceKind.FAQ:
        return processing.faq_sections(source.faq)
    return [processing.Section(processing.normalize(source.text))]


def ingest_source(source_id: uuid.UUID | str) -> KnowledgeSource | None:
    with transaction.atomic():
        source = KnowledgeSource.objects.select_for_update(skip_locked=True).filter(pk=source_id).first()
        if source is None or source.status == SourceStatus.PROCESSING:
            return source
        source.status = SourceStatus.PROCESSING
        source.save(update_fields=["status", "updated_at"])

    try:
        sections = _extract(source)
        full_text = "\n\n".join(s.text for s in sections)[: processing.MAX_EXTRACTED_CHARS]
        chunks = [c for c in processing.chunk_sections(sections) if c.text.strip()]
        if not chunks:
            raise processing.ExtractionError("No usable text was found.")
        embedder = get_embedder()
        vectors, tokens = embedder.embed([c.text for c in chunks])
    except (processing.ExtractionError, EmbeddingError) as exc:
        _fail(source, str(exc))
        return source
    except Exception:
        logger.exception("knowledge_ingest_failed source=%s", source.id)
        _fail(source, "Unexpected error while processing this source.")
        return source

    with transaction.atomic():
        source = KnowledgeSource.objects.select_for_update().get(pk=source.pk)
        source.chunks.all().delete()  # re-index replaces chunks atomically
        KnowledgeChunk.objects.bulk_create(
            [
                KnowledgeChunk(
                    workspace_id=source.workspace_id,
                    organization_id=source.organization_id,
                    source=source,
                    position=n,
                    content=chunk.text,
                    embedding=vector,
                    embedding_model=embedder.model_id,
                    token_count=processing.estimate_tokens(chunk.text),
                    metadata={**chunk.metadata, "title": source.title, "kind": source.kind},
                )
                for n, (chunk, vector) in enumerate(zip(chunks, vectors, strict=True))
            ]
        )
        source.status = SourceStatus.READY
        source.error = ""
        source.char_count = len(full_text)
        source.chunk_count = len(chunks)
        source.content_hash = hashlib.sha256(full_text.encode()).hexdigest()
        source.embedding_model = embedder.model_id
        source.last_indexed_at = timezone.now()
        source.save()
    usage.record_usage(
        organization_id=source.organization_id,
        workspace_id=source.workspace_id,
        metric=Metric.EMBEDDING_TOKENS,
        quantity=tokens,
        idempotency_key=f"embed:{source.id}:{source.content_hash}:{source.last_indexed_at.isoformat()}",
        source_type="knowledge_source",
        source_id=str(source.id),
    )
    return source


def _fail(source: KnowledgeSource, message: str) -> None:
    KnowledgeSource.objects.filter(pk=source.pk).update(status=SourceStatus.FAILED, error=message[:500])
    source.refresh_from_db()


# ---------------------------------------------------------------------------
# Retrieval
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class RetrievedChunk:
    chunk_id: str
    source_id: str
    source_title: str
    content: str
    score: float  # cosine similarity, 1 = identical
    metadata: dict[str, Any]


def search(
    *,
    workspace: Workspace,
    query: str,
    k: int = DEFAULT_TOP_K,
    source_ids: list[Any] | None = None,
    kinds: list[str] | None = None,
    metadata_filter: dict[str, Any] | None = None,
    min_score: float = 0.0,
) -> list[RetrievedChunk]:
    """Vector search within ONE workspace. Callers can only narrow, never widen, the scope."""
    query = (query or "").strip()
    if not query:
        return []
    embedder = get_embedder()
    vectors, _ = embedder.embed([query])
    qs = KnowledgeChunk.objects.filter(
        workspace=workspace,
        embedding_model=embedder.model_id,
        source__enabled=True,
        source__status=SourceStatus.READY,
    )
    if source_ids is not None:
        qs = qs.filter(source_id__in=source_ids)
    if kinds:
        qs = qs.filter(source__kind__in=kinds)
    if metadata_filter:
        qs = qs.filter(source__metadata__contains=metadata_filter)
    rows = (
        qs.select_related("source")
        .annotate(distance=CosineDistance("embedding", vectors[0]))
        .order_by("distance")[: max(1, min(k, MAX_TOP_K))]
    )
    results = [
        RetrievedChunk(
            chunk_id=str(c.id),
            source_id=str(c.source_id),
            source_title=c.source.title,
            content=c.content,
            score=round(1 - float(c.distance), 4),
            metadata=c.metadata,
        )
        for c in rows
    ]
    return [r for r in results if r.score >= min_score]
