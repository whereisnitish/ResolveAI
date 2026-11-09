"""Usage metering and plan-limit enforcement. Never trusts client-supplied quantities."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from django.db import IntegrityError, transaction
from django.db.models import Sum
from django.db.models.functions import Coalesce, Length
from django.utils import timezone

from apps.billing.catalog import INACTIVE_LIMITS, TRIAL_PLAN_CODE
from apps.billing.models import Metric, Plan, Subscription, SubscriptionStatus, UsageLedger
from apps.organizations.models import Invitation, InvitationStatus, Organization, OrganizationMembership
from common.exceptions import ServiceError


class LimitExceeded(ServiceError):
    status_code = 402
    default_code = "plan_limit_reached"


# ---------------------------------------------------------------------------
# Subscription state
# ---------------------------------------------------------------------------
def ensure_catalog() -> None:
    """Make sure every catalog plan exists (self-heals if rows were removed)."""
    from apps.billing.catalog import PLANS

    existing = set(Plan.objects.filter(code__in=[p["code"] for p in PLANS]).values_list("code", flat=True))
    for data in PLANS:
        if data["code"] not in existing:
            Plan.objects.get_or_create(code=data["code"], defaults={k: v for k, v in data.items() if k != "code"})


def get_plan(code: str) -> Plan | None:
    plan = Plan.objects.filter(code=code).first()
    if plan is None:
        ensure_catalog()
        plan = Plan.objects.filter(code=code).first()
    return plan


def ensure_subscription(org: Organization) -> Subscription:
    """Every organization has a subscription row; new orgs start on the trial plan."""
    existing = Subscription.objects.select_related("plan").filter(organization=org).first()
    if existing:
        return existing
    plan = get_plan(TRIAL_PLAN_CODE)
    assert plan is not None
    now = timezone.now()
    try:
        with transaction.atomic():
            return Subscription.objects.create(
                organization=org,
                plan=plan,
                status=SubscriptionStatus.TRIALING,
                trial_ends_at=now + timedelta(days=plan.trial_days),
                current_period_start=now,
                current_period_end=now + timedelta(days=plan.trial_days),
            )
    except IntegrityError:  # concurrent creation
        return Subscription.objects.select_related("plan").get(organization=org)


def is_active(sub: Subscription, now: datetime | None = None) -> bool:
    now = now or timezone.now()
    if sub.status == SubscriptionStatus.TRIALING:
        return sub.trial_ends_at is None or sub.trial_ends_at > now
    return sub.status in (SubscriptionStatus.ACTIVE, SubscriptionStatus.PAST_DUE)


def effective_limits(org: Organization) -> dict[str, int]:
    sub = ensure_subscription(org)
    return dict(sub.plan.limits) if is_active(sub) else dict(INACTIVE_LIMITS)


def current_period(org: Organization) -> tuple[datetime, datetime]:
    """Metering window: the subscription period, else the calendar month."""
    sub = ensure_subscription(org)
    now = timezone.now()
    if sub.current_period_start and sub.current_period_end and sub.current_period_start <= now < sub.current_period_end:
        return sub.current_period_start, sub.current_period_end
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    end = (start + timedelta(days=32)).replace(day=1)
    return start, end


# ---------------------------------------------------------------------------
# Ledger
# ---------------------------------------------------------------------------
def record_usage(
    *,
    organization_id: uuid.UUID,
    metric: str,
    quantity: int,
    idempotency_key: str,
    workspace_id: uuid.UUID | None = None,
    source_type: str = "",
    source_id: str = "",
    occurred_at: datetime | None = None,
) -> bool:
    """Append a usage entry. Returns False if this key was already recorded."""
    if quantity < 0:
        raise ValueError("quantity must be >= 0")
    if quantity == 0:
        return False
    try:
        with transaction.atomic():
            UsageLedger.objects.create(
                organization_id=organization_id,
                workspace_id=workspace_id,
                metric=metric,
                quantity=quantity,
                idempotency_key=idempotency_key,
                source_type=source_type,
                source_id=source_id,
                occurred_at=occurred_at or timezone.now(),
            )
        return True
    except IntegrityError:
        return False


def usage_totals(org: Organization, start: datetime, end: datetime) -> dict[str, int]:
    rows = (
        UsageLedger.objects.filter(organization=org, occurred_at__gte=start, occurred_at__lt=end)
        .values("metric")
        .annotate(total=Sum("quantity"))
    )
    totals = {m: 0 for m in Metric.values}
    totals.update({r["metric"]: int(r["total"]) for r in rows})
    return totals


def seats_used(org: Organization) -> int:
    members = OrganizationMembership.objects.filter(organization=org, is_active=True).count()
    pending = Invitation.objects.filter(
        organization=org, status=InvitationStatus.PENDING, expires_at__gt=timezone.now()
    ).count()
    return members + pending


def knowledge_bytes(org: Organization) -> int:
    from apps.knowledge.models import KnowledgeSource

    agg = KnowledgeSource.objects.filter(organization=org).aggregate(
        files=Coalesce(Sum("size"), 0), text=Coalesce(Sum(Length("text")), 0)
    )
    return int(agg["files"]) + int(agg["text"])


def usage_summary(org: Organization) -> dict[str, object]:
    start, end = current_period(org)
    limits = effective_limits(org)
    totals = usage_totals(org, start, end)
    from apps.workspaces.models import Workspace

    return {
        "period_start": start,
        "period_end": end,
        "limits": limits,
        "usage": {
            **totals,
            "seats": seats_used(org),
            "workspaces": Workspace.objects.filter(organization=org, archived_at__isnull=True).count(),
            "knowledge_mb": round(knowledge_bytes(org) / (1024 * 1024), 2),
        },
    }


# ---------------------------------------------------------------------------
# Enforcement
# ---------------------------------------------------------------------------
def ai_quota_available(org: Organization) -> bool:
    limit = effective_limits(org).get("ai_executions_per_month", 0)
    start, end = current_period(org)
    used = UsageLedger.objects.filter(
        organization=org, metric=Metric.AI_EXECUTIONS, occurred_at__gte=start, occurred_at__lt=end
    ).aggregate(total=Coalesce(Sum("quantity"), 0))["total"]
    return used < limit


def check_seat_available(org: Organization) -> None:
    limit = effective_limits(org).get("seats", 0)
    if seats_used(org) >= limit:
        raise LimitExceeded(
            f"Your plan includes {limit} seats (members + pending invitations). Upgrade to add more people."
        )


def check_workspace_available(org: Organization) -> None:
    from apps.workspaces.models import Workspace

    limit = effective_limits(org).get("workspaces", 0)
    if Workspace.objects.filter(organization=org, archived_at__isnull=True).count() >= limit:
        raise LimitExceeded(f"Your plan includes {limit} workspace(s). Upgrade to create more.")


def check_knowledge_capacity(org: Organization, additional_bytes: int) -> None:
    limit_mb = effective_limits(org).get("knowledge_mb", 0)
    if knowledge_bytes(org) + additional_bytes > limit_mb * 1024 * 1024:
        raise LimitExceeded(f"Your plan includes {limit_mb} MB of knowledge storage. Upgrade or remove sources.")


__all__ = [
    "LimitExceeded",
    "ai_quota_available",
    "check_knowledge_capacity",
    "check_seat_available",
    "check_workspace_available",
    "current_period",
    "effective_limits",
    "ensure_subscription",
    "is_active",
    "record_usage",
    "usage_summary",
]
