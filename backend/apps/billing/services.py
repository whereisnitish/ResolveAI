from __future__ import annotations

import logging
from typing import Any

from django.db import transaction
from django.utils import timezone

from apps.audit import services as audit
from apps.billing.models import (
    Invoice,
    InvoiceStatus,
    Subscription,
    SubscriptionStatus,
    WebhookEvent,
    WebhookStatus,
)
from apps.billing.providers import BillingEvent, CheckoutSession, get_payment_provider, provider_for
from apps.billing.usage import ensure_subscription, get_plan
from apps.organizations.models import Organization
from common.exceptions import ServiceError

logger = logging.getLogger(__name__)


def start_checkout(
    *, org: Organization, plan_code: str, currency: str, actor: Any, request: Any = None
) -> CheckoutSession:
    plan = get_plan(plan_code)
    if plan is None or not plan.is_public or plan.is_trial:
        raise ServiceError("Unknown plan.", code="invalid_plan")
    currency = currency.upper()
    if currency not in plan.prices:
        raise ServiceError(f"{plan.name} isn't available in {currency}.", code="invalid_currency")
    provider = get_payment_provider(provider_for(org))
    from django.conf import settings

    session = provider.create_checkout(
        org=org,
        plan=plan,
        currency=currency,
        success_url=f"{settings.FRONTEND_URL}/app/billing?checkout=success",
        cancel_url=f"{settings.FRONTEND_URL}/app/billing?checkout=cancelled",
    )
    audit.record(
        "billing.checkout_started",
        actor=actor,
        request=request,
        organization_id=org.id,
        metadata={"plan": plan.code, "currency": currency, "provider": session.provider},
    )
    return session


def process_webhook(provider_name: str, headers: dict[str, str], body: bytes) -> tuple[WebhookEvent, bool]:
    """Verify, record and apply a provider webhook exactly once.

    Returns (event, applied_now). A redelivery of an already processed event is a no-op
    (critical security test #6). A previously *failed* event is retried.
    """
    provider = get_payment_provider(provider_name)
    parsed = provider.parse_webhook({k.lower(): v for k, v in headers.items()}, body)  # raises InvalidSignature
    if not parsed.event_id:
        raise ServiceError("Webhook has no event id.", code="invalid_webhook")

    with transaction.atomic():
        event, created = WebhookEvent.objects.select_for_update().get_or_create(
            provider=provider_name,
            event_id=parsed.event_id,
            defaults={"event_type": parsed.event_type, "payload": parsed.payload},
        )
        if not created and event.status in (WebhookStatus.PROCESSED, WebhookStatus.IGNORED):
            return event, False
        event.attempts += 1
        try:
            with transaction.atomic():
                for billing_event in parsed.events:
                    apply_event(provider_name, billing_event)
            event.status = WebhookStatus.PROCESSED if parsed.events else WebhookStatus.IGNORED
            event.error = ""
            event.processed_at = timezone.now()
        except Exception as exc:
            logger.exception("billing_webhook_failed provider=%s event=%s", provider_name, parsed.event_id)
            event.status = WebhookStatus.FAILED
            event.error = str(exc)[:1000]
        event.save()
    return event, event.status != WebhookStatus.FAILED


def _subscription_for(provider: str, ev: BillingEvent) -> Subscription | None:
    if ev.subscription_id:
        sub = Subscription.objects.filter(provider=provider, provider_subscription_id=ev.subscription_id).first()
        if sub:
            return sub
    if ev.org_id:
        org = Organization.objects.filter(id=ev.org_id).first()
        if org:
            return ensure_subscription(org)
    return None


def apply_event(provider: str, ev: BillingEvent) -> None:
    sub = _subscription_for(provider, ev)
    if sub is None:
        raise ValueError(f"No organization for {ev.kind} (subscription {ev.subscription_id or '-'})")
    sub = Subscription.objects.select_for_update().get(pk=sub.pk)

    if ev.kind in ("subscription_active", "subscription_updated", "subscription_canceled"):
        if ev.plan_code:
            plan = get_plan(ev.plan_code)
            if plan is None:
                raise ValueError(f"Unknown plan {ev.plan_code}")
            sub.plan = plan
        sub.provider = provider
        sub.provider_customer_id = ev.customer_id or sub.provider_customer_id
        sub.provider_subscription_id = ev.subscription_id or sub.provider_subscription_id
        sub.currency = ev.currency or sub.currency
        if ev.kind == "subscription_canceled":
            sub.status = SubscriptionStatus.CANCELED
        elif ev.status:
            sub.status = ev.status
        if ev.period_start:
            sub.current_period_start = ev.period_start
        if ev.period_end:
            sub.current_period_end = ev.period_end
        if ev.cancel_at_period_end is not None:
            sub.cancel_at_period_end = ev.cancel_at_period_end
        if sub.status == SubscriptionStatus.ACTIVE:
            sub.trial_ends_at = None
        sub.save()
        audit.record(
            f"billing.{ev.kind}",
            organization_id=sub.organization_id,
            metadata={"provider": provider, "plan": sub.plan.code, "status": sub.status},
        )
    elif ev.kind in ("invoice_paid", "invoice_failed"):
        inv = ev.invoice
        Invoice.objects.update_or_create(
            provider=provider,
            provider_invoice_id=str(inv["id"]),
            defaults={
                "organization_id": sub.organization_id,
                "amount_minor": int(inv.get("amount_minor") or 0),
                "currency": inv.get("currency") or sub.currency or "USD",
                "status": InvoiceStatus.PAID if ev.kind == "invoice_paid" else InvoiceStatus.FAILED,
                "hosted_url": inv.get("hosted_url") or "",
                "period_start": inv.get("period_start"),
                "period_end": inv.get("period_end"),
                "issued_at": inv.get("issued_at") or timezone.now(),
            },
        )
        if ev.kind == "invoice_failed" and sub.status == SubscriptionStatus.ACTIVE:
            sub.status = SubscriptionStatus.PAST_DUE
            sub.save(update_fields=["status", "updated_at"])
