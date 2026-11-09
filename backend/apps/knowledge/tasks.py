from __future__ import annotations

from celery import shared_task


@shared_task(acks_late=True, soft_time_limit=540, time_limit=600)
def ingest_source_task(source_id: str) -> str | None:
    from apps.knowledge.services import ingest_source

    source = ingest_source(source_id)
    return source.status if source else None
