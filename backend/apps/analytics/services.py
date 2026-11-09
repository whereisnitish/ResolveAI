"""Support analytics. Every query is scoped by the caller-supplied workspace id set,
which the API derives from the caller's verified access (never from client input)."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from django.db.models import Avg, Count, DurationField, Exists, ExpressionWrapper, F, OuterRef, Q, Subquery, Sum
from django.db.models.functions import TruncDate
from django.utils import timezone

from apps.ai_agents.models import AIExecution, ExecutionSource, ExecutionStatus
from apps.conversations.models import (
    ActorType,
    Conversation,
    ConversationEvent,
    ConversationEventType,
    ConversationStatus,
    Message,
    MessageKind,
)

MAX_RANGE_DAYS = 366


def parse_range(start: str | None, end: str | None) -> tuple[datetime, datetime]:
    today = timezone.localdate()
    try:
        end_d = date.fromisoformat(end) if end else today
        start_d = date.fromisoformat(start) if start else end_d - timedelta(days=29)
    except ValueError as exc:
        raise ValueError("Dates must be YYYY-MM-DD.") from exc
    if start_d > end_d:
        raise ValueError("start must be before end.")
    if (end_d - start_d).days > MAX_RANGE_DAYS:
        raise ValueError(f"Range can't exceed {MAX_RANGE_DAYS} days.")
    tz = timezone.get_current_timezone()
    return (
        datetime.combine(start_d, datetime.min.time(), tzinfo=tz),
        datetime.combine(end_d + timedelta(days=1), datetime.min.time(), tzinfo=tz),
    )


def _seconds(value: timedelta | None) -> float | None:
    return round(value.total_seconds(), 1) if value is not None else None


def compute(workspace_ids: list[Any], start: datetime, end: datetime) -> dict[str, Any]:
    convs = Conversation.objects.filter(workspace_id__in=workspace_ids)
    created = convs.filter(created_at__gte=start, created_at__lt=end)
    resolved = convs.filter(
        resolved_at__gte=start, resolved_at__lt=end, status__in=[ConversationStatus.RESOLVED, ConversationStatus.CLOSED]
    )

    replies = Message.objects.filter(conversation=OuterRef("pk"), kind=MessageKind.REPLY)
    ai_reply = replies.filter(author_type=ActorType.AI)
    human_reply = replies.filter(author_type=ActorType.AGENT)
    first_response = (
        Message.objects.filter(
            conversation=OuterRef("pk"), kind=MessageKind.REPLY, author_type__in=[ActorType.AGENT, ActorType.AI]
        )
        .order_by("created_at")
        .values("created_at")[:1]
    )
    handoff = ConversationEvent.objects.filter(conversation=OuterRef("pk"), type=ConversationEventType.HANDOFF)

    ai_involved = created.filter(Exists(ai_reply))
    ai_resolved = resolved.filter(Exists(ai_reply)).exclude(Exists(human_reply)).count()
    resolved_count = resolved.count()
    ai_involved_count = ai_involved.count()
    handed_off = ai_involved.filter(Exists(handoff)).count()

    frt = (
        created.annotate(first=Subquery(first_response))
        .filter(first__isnull=False)
        .aggregate(avg=Avg(ExpressionWrapper(F("first") - F("created_at"), output_field=DurationField())))["avg"]
    )
    resolution = resolved.aggregate(
        avg=Avg(ExpressionWrapper(F("resolved_at") - F("created_at"), output_field=DurationField()))
    )["avg"]

    executions = AIExecution.objects.filter(workspace_id__in=workspace_ids, created_at__gte=start, created_at__lt=end)
    ai = executions.aggregate(
        total=Count("id", filter=~Q(status=ExecutionStatus.SKIPPED)),
        answered=Count("id", filter=Q(status=ExecutionStatus.ANSWERED, source=ExecutionSource.CONVERSATION)),
        handed_off=Count("id", filter=Q(status=ExecutionStatus.HANDED_OFF, source=ExecutionSource.CONVERSATION)),
        failed=Count("id", filter=Q(status=ExecutionStatus.FAILED)),
        input_tokens=Sum("input_tokens"),
        output_tokens=Sum("output_tokens"),
        avg_latency_ms=Avg("latency_ms", filter=~Q(status=ExecutionStatus.SKIPPED)),
    )

    # Agent performance
    agent_rows = (
        Message.objects.filter(
            workspace_id__in=workspace_ids,
            author_type=ActorType.AGENT,
            kind=MessageKind.REPLY,
            created_at__gte=start,
            created_at__lt=end,
        )
        .values("author_user_id", "author_user__full_name", "author_user__email")
        .annotate(replies=Count("id"), conversations=Count("conversation", distinct=True))
    )
    resolutions = dict(
        ConversationEvent.objects.filter(
            workspace_id__in=workspace_ids,
            type=ConversationEventType.STATUS_CHANGED,
            data__to=ConversationStatus.RESOLVED,
            actor_user__isnull=False,
            created_at__gte=start,
            created_at__lt=end,
        )
        .values("actor_user_id")
        .annotate(n=Count("id"))
        .values_list("actor_user_id", "n")
    )
    agents = sorted(
        (
            {
                "user_id": str(r["author_user_id"]),
                "name": r["author_user__full_name"] or r["author_user__email"],
                "replies": r["replies"],
                "conversations": r["conversations"],
                "resolved": resolutions.get(r["author_user_id"], 0),
            }
            for r in agent_rows
            if r["author_user_id"]
        ),
        key=lambda a: -a["replies"],
    )

    # Daily series
    def series(qs: Any, field: str) -> dict[str, int]:
        return {
            str(row["day"]): row["n"]
            for row in qs.annotate(day=TruncDate(field)).values("day").annotate(n=Count("id")).order_by("day")
        }

    created_by_day = series(created, "created_at")
    resolved_by_day = series(resolved, "resolved_at")
    ai_by_day = series(
        Message.objects.filter(
            workspace_id__in=workspace_ids, author_type=ActorType.AI, created_at__gte=start, created_at__lt=end
        ),
        "created_at",
    )
    days = []
    cursor = start.date()
    while cursor < end.date():
        key = str(cursor)
        days.append(
            {
                "date": key,
                "created": created_by_day.get(key, 0),
                "resolved": resolved_by_day.get(key, 0),
                "ai_replies": ai_by_day.get(key, 0),
            }
        )
        cursor += timedelta(days=1)

    return {
        "range": {"start": start.date().isoformat(), "end": (end - timedelta(days=1)).date().isoformat()},
        "conversations": {
            "total": created.count(),
            "open": convs.filter(status=ConversationStatus.OPEN).count(),
            "pending": convs.filter(status=ConversationStatus.PENDING).count(),
            "resolved": resolved_count,
            "by_channel": dict(created.values_list("channel").annotate(n=Count("id")).values_list("channel", "n")),
        },
        "ai": {
            "involved_conversations": ai_involved_count,
            "resolved_without_human": ai_resolved,
            "resolution_rate": round(ai_resolved / resolved_count, 4) if resolved_count else None,
            "handoff_rate": round(handed_off / ai_involved_count, 4) if ai_involved_count else None,
            "executions": ai["total"] or 0,
            "answered": ai["answered"] or 0,
            "handed_off": ai["handed_off"] or 0,
            "failed": ai["failed"] or 0,
            "input_tokens": ai["input_tokens"] or 0,
            "output_tokens": ai["output_tokens"] or 0,
            "avg_latency_ms": round(ai["avg_latency_ms"]) if ai["avg_latency_ms"] else None,
        },
        "response_times": {
            "avg_first_response_seconds": _seconds(frt),
            "avg_resolution_seconds": _seconds(resolution),
        },
        "agents": agents,
        "daily": days,
        "generated_at": timezone.now(),
    }
