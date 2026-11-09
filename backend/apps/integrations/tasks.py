from __future__ import annotations

from typing import Any

from celery import shared_task

from apps.integrations.services import MAX_ATTEMPTS, RetryableDeliveryError


@shared_task(
    bind=True,
    autoretry_for=(RetryableDeliveryError,),
    retry_backoff=30,
    retry_backoff_max=3600,
    retry_jitter=True,
    max_retries=MAX_ATTEMPTS - 1,
)
def deliver_task(self, delivery_id: str) -> str | None:  # type: ignore[no-untyped-def]
    from apps.integrations.services import deliver

    delivery = deliver(delivery_id)
    return delivery.status if delivery else None


@shared_task
def fan_out_task(event: str, conversation_id: str, message_id: str | None = None) -> int:
    from apps.integrations.services import fan_out

    return len(fan_out(event, conversation_id, message_id))


def on_event(event: str, payload: dict[str, Any]) -> None:
    cid = payload["conversation_id"]
    if event == "conversation.created":
        fan_out_task.delay("conversation.created", cid)
    elif event == "conversation.status_changed" and payload.get("to") == "resolved":
        fan_out_task.delay("conversation.resolved", cid)
    elif event == "conversation.assigned":
        fan_out_task.delay("conversation.assigned", cid)
    elif event == "message.created" and payload.get("author_type") == "customer" and payload.get("kind") == "reply":
        fan_out_task.delay("message.created", cid, payload["message_id"])
