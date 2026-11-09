"""Publish real-time events to WebSocket groups.

Design (ADR-0005):
* Dashboard events carry only identifiers (``conversation_id``, ``message_id``).
  Clients refetch through the REST API, which re-checks authorization on every
  call, so a stale socket can never leak data after access is revoked.
* Visitor events carry the visitor's own non-internal messages, because the
  widget has no other way to receive them in real time.
* Events are sent after the DB transaction commits, so clients never see
  rows that were rolled back.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.db import transaction

logger = logging.getLogger(__name__)


def workspace_group(workspace_id: uuid.UUID | str) -> str:
    return f"workspace.{workspace_id}"


def visitor_group(customer_id: uuid.UUID | str) -> str:
    return f"visitor.{customer_id}"


def _send(group: str, payload: dict[str, Any]) -> None:
    layer = get_channel_layer()
    if layer is None:
        return
    try:
        async_to_sync(layer.group_send)(group, {"type": "broadcast", "payload": payload})
    except Exception:  # real-time is best effort; REST remains the source of truth
        logger.exception("realtime_publish_failed group=%s type=%s", group, payload.get("type"))


def publish_workspace(workspace_id: uuid.UUID | str, payload: dict[str, Any]) -> None:
    transaction.on_commit(lambda: _send(workspace_group(workspace_id), payload))


def publish_visitor(customer_id: uuid.UUID | str, payload: dict[str, Any]) -> None:
    transaction.on_commit(lambda: _send(visitor_group(customer_id), payload))


def send_now(group: str, payload: dict[str, Any]) -> None:
    """For ephemeral signals (typing) that aren't tied to a transaction."""
    _send(group, payload)
