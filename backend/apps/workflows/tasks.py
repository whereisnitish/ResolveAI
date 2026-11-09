from __future__ import annotations

from typing import Any

from celery import shared_task

from apps.workflows.models import Trigger


@shared_task(acks_late=True)
def dispatch_workflows_task(
    trigger: str, conversation_id: str, message_id: str | None = None, occurrence: str = ""
) -> int:
    from apps.workflows.engine import dispatch

    return dispatch(trigger, conversation_id, message_id, occurrence)


@shared_task
def scan_unanswered_task() -> int:
    from apps.workflows.engine import scan_unanswered

    return scan_unanswered()


def on_event(event: str, payload: dict[str, Any]) -> None:
    """Domain-event subscriber. Ignores events caused by workflows (no loops)."""
    if payload.get("source") == "workflow":
        return
    cid = payload["conversation_id"]
    if event == "conversation.created":
        dispatch_workflows_task.delay(Trigger.CONVERSATION_CREATED, cid, None, "created")
    elif event == "message.created" and payload.get("author_type") == "customer" and payload.get("kind") == "reply":
        dispatch_workflows_task.delay(Trigger.CUSTOMER_MESSAGE, cid, payload["message_id"])
    elif event == "conversation.status_changed" and payload.get("to") == "resolved":
        from django.utils import timezone

        dispatch_workflows_task.delay(Trigger.CONVERSATION_RESOLVED, cid, None, timezone.now().isoformat())
