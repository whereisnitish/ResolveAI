from __future__ import annotations

from typing import Any

from celery import shared_task


@shared_task(acks_late=True, soft_time_limit=170, time_limit=180)
def ai_reply_task(conversation_id: str, message_id: str) -> str | None:
    from apps.ai_agents.services import handle_customer_message

    execution = handle_customer_message(conversation_id, message_id)
    return execution.status if execution else None


def on_message_created(event: str, payload: dict[str, Any]) -> None:
    """Domain-event subscriber: a customer wrote in → let the deployed AI agent respond."""
    if payload.get("author_type") == "customer" and payload.get("kind") == "reply":
        ai_reply_task.delay(payload["conversation_id"], payload["message_id"])
