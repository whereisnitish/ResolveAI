from __future__ import annotations

import os
import uuid

from django.conf import settings
from django.db import models
from pgvector.django import HnswIndex, VectorField

from apps.workspaces.models import WorkspaceOwnedModel

EMBEDDING_DIMENSIONS = 1536


class SourceKind(models.TextChoices):
    FILE = "file", "File (PDF, TXT, Markdown)"
    URL = "url", "Website URL"
    FAQ = "faq", "FAQ"
    TEXT = "text", "Text"


class SourceStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    PROCESSING = "processing", "Processing"
    READY = "ready", "Ready"
    FAILED = "failed", "Failed"


def knowledge_upload_to(instance: KnowledgeSource, filename: str) -> str:
    ext = os.path.splitext(filename)[1].lower()[:10]
    return f"knowledge/{instance.workspace_id}/{uuid.uuid4().hex}{ext}"


class KnowledgeSource(WorkspaceOwnedModel):
    kind = models.CharField(max_length=10, choices=SourceKind.choices)
    title = models.CharField(max_length=200)
    status = models.CharField(max_length=20, choices=SourceStatus.choices, default=SourceStatus.PENDING)
    error = models.CharField(max_length=500, blank=True, default="")
    enabled = models.BooleanField(default=True)
    # Kind-specific inputs
    file = models.FileField(upload_to=knowledge_upload_to, max_length=255, blank=True)
    filename = models.CharField(max_length=255, blank=True, default="")
    content_type = models.CharField(max_length=100, blank=True, default="")
    size = models.PositiveBigIntegerField(default=0)
    url = models.URLField(max_length=1000, blank=True, default="")
    faq = models.JSONField(default=list, blank=True)  # [{"question": ..., "answer": ...}]
    text = models.TextField(blank=True, default="", max_length=200_000)
    # Free-form key/value labels for retrieval filtering (e.g. {"product": "billing"})
    metadata = models.JSONField(default=dict, blank=True)
    # Ingestion results
    content_hash = models.CharField(max_length=64, blank=True, default="")
    char_count = models.PositiveIntegerField(default=0)
    chunk_count = models.PositiveIntegerField(default=0)
    embedding_model = models.CharField(max_length=100, blank=True, default="")
    last_indexed_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["workspace", "status"], name="ksource_ws_status")]

    def __str__(self) -> str:
        return self.title


class KnowledgeChunk(WorkspaceOwnedModel):
    source = models.ForeignKey(KnowledgeSource, on_delete=models.CASCADE, related_name="chunks")
    position = models.PositiveIntegerField()
    content = models.TextField()
    embedding = VectorField(dimensions=EMBEDDING_DIMENSIONS)
    # Vectors from different embedding models live in different spaces; retrieval
    # only compares chunks embedded with the currently configured model.
    embedding_model = models.CharField(max_length=100)
    token_count = models.PositiveIntegerField(default=0)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["source", "position"]
        indexes = [
            models.Index(fields=["workspace", "embedding_model"], name="kchunk_ws_model"),
            HnswIndex(
                name="kchunk_embedding_hnsw",
                fields=["embedding"],
                m=16,
                ef_construction=64,
                opclasses=["vector_cosine_ops"],
            ),
        ]
        constraints = [models.UniqueConstraint(fields=["source", "position"], name="kchunk_unique_position")]
