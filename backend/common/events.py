"""In-process domain events for the modular monolith.

Core domains (conversations) emit events; feature modules (AI agents, workflows,
integrations) subscribe in their AppConfig.ready(). Handlers run *after* the
emitting transaction commits, so they never observe rolled-back state, and
they should enqueue Celery tasks rather than doing slow work inline.

Event names:
    conversation.created        {conversation_id, workspace_id, channel, source}
    message.created             {conversation_id, workspace_id, message_id, author_type, kind, source}
    conversation.status_changed {conversation_id, workspace_id, from, to, source}
    conversation.assigned       {conversation_id, workspace_id, assignee_id, team_id, source}

`source` is "user", "customer", "ai", "workflow" or "system" — subscribers use it to
avoid loops (e.g. workflows ignore events caused by workflows).
"""

from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Callable
from typing import Any

from django.db import transaction

logger = logging.getLogger(__name__)

Handler = Callable[[str, dict[str, Any]], None]
_handlers: dict[str, list[Handler]] = defaultdict(list)


def subscribe(event: str, handler: Handler) -> None:
    if handler not in _handlers[event]:
        _handlers[event].append(handler)


def emit(event: str, **payload: Any) -> None:
    def _dispatch() -> None:
        for handler in list(_handlers.get(event, ())):
            try:
                handler(event, payload)
            except Exception:  # one subscriber must not break others or the caller
                logger.exception(
                    "event_handler_failed event=%s handler=%s", event, getattr(handler, "__name__", handler)
                )

    transaction.on_commit(_dispatch)
