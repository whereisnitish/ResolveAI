"""Payment provider abstraction: Stripe (international), Razorpay (India), Mock (dev).

Each provider:
* create_checkout(...) -> CheckoutSession (URL the customer is redirected to)
* parse_webhook(headers, body) -> ParsedWebhook (verifies the signature first)

Webhook payloads are normalized into provider-agnostic `BillingEvent`s so the
subscription logic (services.apply_event) is written once.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

import httpx
from django.conf import settings
from django.utils import timezone

from apps.billing.models import Plan
from apps.organizations.models import Organization

STRIPE_TOLERANCE_SECONDS = 300


class InvalidSignature(Exception):
    pass


class ProviderUnavailable(Exception):
    pass


@dataclass
class CheckoutSession:
    provider: str
    url: str
    reference: str = ""


@dataclass
class BillingEvent:
    kind: str  # subscription_active | subscription_updated | subscription_canceled | invoice_paid | invoice_failed
    org_id: str | None = None
    plan_code: str | None = None
    currency: str | None = None
    customer_id: str = ""
    subscription_id: str = ""
    status: str | None = None
    period_start: datetime | None = None
    period_end: datetime | None = None
    cancel_at_period_end: bool | None = None
    invoice: dict[str, Any] = field(default_factory=dict)


@dataclass
class ParsedWebhook:
    event_id: str
    event_type: str
    payload: dict[str, Any]
    events: list[BillingEvent]


class PaymentProvider(Protocol):
    name: str

    def create_checkout(
        self, *, org: Organization, plan: Plan, currency: str, success_url: str, cancel_url: str
    ) -> CheckoutSession: ...

    def parse_webhook(self, headers: dict[str, str], body: bytes) -> ParsedWebhook: ...


def _ts(value: Any) -> datetime | None:
    return datetime.fromtimestamp(int(value), tz=UTC) if value else None


def _hmac_hex(secret: str, message: bytes) -> str:
    return hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()


def _loads(body: bytes) -> dict[str, Any]:
    try:
        data = json.loads(body)
    except ValueError as exc:
        raise InvalidSignature("Malformed JSON body") from exc
    if not isinstance(data, dict):
        raise InvalidSignature("Unexpected payload")
    return data


# ---------------------------------------------------------------------------
# Stripe
# ---------------------------------------------------------------------------
_STRIPE_STATUS = {
    "active": "active",
    "trialing": "active",
    "past_due": "past_due",
    "unpaid": "past_due",
    "incomplete": "past_due",
    "canceled": "canceled",
    "incomplete_expired": "canceled",
}


class StripeProvider:
    name = "stripe"
    api = "https://api.stripe.com/v1"

    def __init__(self, secret_key: str, webhook_secret: str, transport: httpx.BaseTransport | None = None) -> None:
        self.secret_key = secret_key
        self.webhook_secret = webhook_secret
        self.transport = transport

    def create_checkout(
        self, *, org: Organization, plan: Plan, currency: str, success_url: str, cancel_url: str
    ) -> CheckoutSession:
        form: dict[str, Any] = {
            "mode": "subscription",
            "success_url": success_url,
            "cancel_url": cancel_url,
            "client_reference_id": str(org.id),
            "metadata[org_id]": str(org.id),
            "metadata[plan]": plan.code,
            "subscription_data[metadata][org_id]": str(org.id),
            "subscription_data[metadata][plan]": plan.code,
            "line_items[0][quantity]": 1,
        }
        price_id = plan.provider_prices.get("stripe", {}).get(currency)
        if price_id:
            form["line_items[0][price]"] = price_id
        else:
            form.update(
                {
                    "line_items[0][price_data][currency]": currency.lower(),
                    "line_items[0][price_data][unit_amount]": plan.prices[currency],
                    "line_items[0][price_data][recurring][interval]": "month",
                    "line_items[0][price_data][product_data][name]": f"ResolveAI {plan.name}",
                }
            )
        with httpx.Client(timeout=20, transport=self.transport) as client:
            response = client.post(f"{self.api}/checkout/sessions", data=form, auth=(self.secret_key, ""))
        if response.status_code >= 400:
            raise ProviderUnavailable(f"Stripe checkout failed ({response.status_code}).")
        body = response.json()
        return CheckoutSession(provider=self.name, url=body["url"], reference=body["id"])

    def parse_webhook(self, headers: dict[str, str], body: bytes) -> ParsedWebhook:
        header = headers.get("stripe-signature", "")
        parts: dict[str, list[str]] = {}
        for item in header.split(","):
            key, _, value = item.strip().partition("=")
            parts.setdefault(key, []).append(value)
        timestamp = (parts.get("t") or [""])[0]
        if not timestamp.isdigit() or abs(time.time() - int(timestamp)) > STRIPE_TOLERANCE_SECONDS:
            raise InvalidSignature("Stale or missing timestamp")
        expected = _hmac_hex(self.webhook_secret, f"{timestamp}.".encode() + body)
        if not any(hmac.compare_digest(expected, sig) for sig in parts.get("v1", [])):
            raise InvalidSignature("Signature mismatch")
        data = _loads(body)
        obj = data.get("data", {}).get("object", {})
        etype = data.get("type", "")
        events: list[BillingEvent] = []
        if etype == "checkout.session.completed" and obj.get("mode") == "subscription":
            events.append(
                BillingEvent(
                    kind="subscription_active",
                    org_id=obj.get("client_reference_id") or obj.get("metadata", {}).get("org_id"),
                    plan_code=obj.get("metadata", {}).get("plan"),
                    currency=(obj.get("currency") or "").upper() or None,
                    customer_id=obj.get("customer") or "",
                    subscription_id=obj.get("subscription") or "",
                    status="active",
                )
            )
        elif etype in (
            "customer.subscription.created",
            "customer.subscription.updated",
            "customer.subscription.deleted",
        ):
            meta = obj.get("metadata", {})
            events.append(
                BillingEvent(
                    kind="subscription_canceled" if etype.endswith("deleted") else "subscription_updated",
                    org_id=meta.get("org_id"),
                    plan_code=meta.get("plan"),
                    customer_id=obj.get("customer") or "",
                    subscription_id=obj.get("id") or "",
                    status=_STRIPE_STATUS.get(obj.get("status", "")),
                    period_start=_ts(obj.get("current_period_start")),
                    period_end=_ts(obj.get("current_period_end")),
                    cancel_at_period_end=obj.get("cancel_at_period_end"),
                )
            )
        elif etype in ("invoice.paid", "invoice.payment_failed"):
            events.append(
                BillingEvent(
                    kind="invoice_paid" if etype == "invoice.paid" else "invoice_failed",
                    customer_id=obj.get("customer") or "",
                    subscription_id=obj.get("subscription") or "",
                    invoice={
                        "id": obj.get("id"),
                        "amount_minor": obj.get("amount_paid") if etype == "invoice.paid" else obj.get("amount_due"),
                        "currency": (obj.get("currency") or "").upper(),
                        "hosted_url": obj.get("hosted_invoice_url") or "",
                        "period_start": _ts(obj.get("period_start")),
                        "period_end": _ts(obj.get("period_end")),
                        "issued_at": _ts(obj.get("created")) or timezone.now(),
                    },
                )
            )
        return ParsedWebhook(event_id=data.get("id", ""), event_type=etype, payload=data, events=events)


# ---------------------------------------------------------------------------
# Razorpay
# ---------------------------------------------------------------------------
class RazorpayProvider:
    name = "razorpay"
    api = "https://api.razorpay.com/v1"

    def __init__(
        self, key_id: str, key_secret: str, webhook_secret: str, transport: httpx.BaseTransport | None = None
    ) -> None:
        self.key_id, self.key_secret, self.webhook_secret, self.transport = (
            key_id,
            key_secret,
            webhook_secret,
            transport,
        )

    def create_checkout(
        self, *, org: Organization, plan: Plan, currency: str, success_url: str, cancel_url: str
    ) -> CheckoutSession:
        plan_id = plan.provider_prices.get("razorpay", {}).get(currency)
        if not plan_id:
            raise ProviderUnavailable(f"Razorpay plan id for {plan.code}/{currency} is not configured.")
        payload = {
            "plan_id": plan_id,
            "total_count": 120,
            "customer_notify": 1,
            "notes": {"org_id": str(org.id), "plan": plan.code},
        }
        with httpx.Client(timeout=20, transport=self.transport) as client:
            response = client.post(f"{self.api}/subscriptions", json=payload, auth=(self.key_id, self.key_secret))
        if response.status_code >= 400:
            raise ProviderUnavailable(f"Razorpay subscription failed ({response.status_code}).")
        body = response.json()
        return CheckoutSession(provider=self.name, url=body["short_url"], reference=body["id"])

    def parse_webhook(self, headers: dict[str, str], body: bytes) -> ParsedWebhook:
        signature = headers.get("x-razorpay-signature", "")
        if not signature or not hmac.compare_digest(_hmac_hex(self.webhook_secret, body), signature):
            raise InvalidSignature("Signature mismatch")
        data = _loads(body)
        etype = data.get("event", "")
        payload = data.get("payload", {})
        sub = payload.get("subscription", {}).get("entity", {})
        payment = payload.get("payment", {}).get("entity", {})
        notes = sub.get("notes") or {}
        base = {
            "org_id": notes.get("org_id"),
            "plan_code": notes.get("plan"),
            "customer_id": sub.get("customer_id") or "",
            "subscription_id": sub.get("id") or "",
            "period_start": _ts(sub.get("current_start")),
            "period_end": _ts(sub.get("current_end")),
            "currency": "INR",
        }
        events: list[BillingEvent] = []
        if etype in ("subscription.activated", "subscription.charged", "subscription.resumed"):
            events.append(BillingEvent(kind="subscription_active", status="active", **base))
            if etype == "subscription.charged" and payment:
                events.append(
                    BillingEvent(
                        kind="invoice_paid",
                        subscription_id=base["subscription_id"],
                        invoice={
                            "id": payment.get("invoice_id") or payment.get("id"),
                            "amount_minor": payment.get("amount"),
                            "currency": (payment.get("currency") or "INR").upper(),
                            "hosted_url": "",
                            "period_start": base["period_start"],
                            "period_end": base["period_end"],
                            "issued_at": _ts(payment.get("created_at")) or timezone.now(),
                        },
                    )
                )
        elif etype in ("subscription.cancelled", "subscription.completed"):
            events.append(BillingEvent(kind="subscription_canceled", status="canceled", **base))
        elif etype in ("subscription.halted", "subscription.pending"):
            events.append(BillingEvent(kind="subscription_updated", status="past_due", **base))
        event_id = headers.get("x-razorpay-event-id") or hashlib.sha256(body).hexdigest()
        return ParsedWebhook(event_id=event_id, event_type=etype, payload=data, events=events)


# ---------------------------------------------------------------------------
# Mock (development): signed events through the same pipeline
# ---------------------------------------------------------------------------
class MockProvider:
    name = "mock"

    @staticmethod
    def secret() -> str:
        return hashlib.sha256(f"mock-billing:{settings.SECRET_KEY}".encode()).hexdigest()

    def sign(self, body: bytes) -> str:
        return _hmac_hex(self.secret(), body)

    def build_event(self, *, org: Organization, plan: Plan, currency: str) -> bytes:
        now = int(time.time())
        event = {
            "id": f"evt_mock_{hashlib.sha256(f'{org.id}{plan.code}{now}'.encode()).hexdigest()[:20]}",
            "type": "subscription.paid",
            "org_id": str(org.id),
            "plan": plan.code,
            "currency": currency,
            "subscription_id": f"sub_mock_{str(org.id)[:8]}",
            "invoice_id": f"in_mock_{now}",
            "amount_minor": plan.prices[currency],
            "period_start": now,
            "period_end": int((timezone.now() + timedelta(days=30)).timestamp()),
        }
        return json.dumps(event).encode()

    def create_checkout(
        self, *, org: Organization, plan: Plan, currency: str, success_url: str, cancel_url: str
    ) -> CheckoutSession:
        from apps.billing.services import process_webhook

        body = self.build_event(org=org, plan=plan, currency=currency)
        process_webhook("mock", {"x-mock-signature": self.sign(body)}, body)
        return CheckoutSession(provider=self.name, url=success_url, reference="mock")

    def parse_webhook(self, headers: dict[str, str], body: bytes) -> ParsedWebhook:
        if not hmac.compare_digest(self.sign(body), headers.get("x-mock-signature", "")):
            raise InvalidSignature("Signature mismatch")
        d = _loads(body)
        start, end = _ts(d.get("period_start")), _ts(d.get("period_end"))
        events = [
            BillingEvent(
                kind="subscription_active",
                org_id=d.get("org_id"),
                plan_code=d.get("plan"),
                currency=d.get("currency"),
                customer_id=f"cus_mock_{str(d.get('org_id'))[:8]}",
                subscription_id=d.get("subscription_id", ""),
                status="active",
                period_start=start,
                period_end=end,
            ),
            BillingEvent(
                kind="invoice_paid",
                subscription_id=d.get("subscription_id", ""),
                invoice={
                    "id": d.get("invoice_id"),
                    "amount_minor": d.get("amount_minor"),
                    "currency": d.get("currency"),
                    "hosted_url": "",
                    "period_start": start,
                    "period_end": end,
                    "issued_at": start or timezone.now(),
                },
            ),
        ]
        return ParsedWebhook(event_id=d.get("id", ""), event_type=d.get("type", ""), payload=d, events=events)


def get_payment_provider(name: str) -> PaymentProvider:
    if name == "stripe" and settings.STRIPE_SECRET_KEY and settings.STRIPE_WEBHOOK_SECRET:
        return StripeProvider(settings.STRIPE_SECRET_KEY, settings.STRIPE_WEBHOOK_SECRET)
    if (
        name == "razorpay"
        and settings.RAZORPAY_KEY_ID
        and settings.RAZORPAY_KEY_SECRET
        and settings.RAZORPAY_WEBHOOK_SECRET
    ):
        return RazorpayProvider(
            settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET, settings.RAZORPAY_WEBHOOK_SECRET
        )
    if name == "mock" and settings.BILLING_ALLOW_MOCK:
        return MockProvider()
    raise ProviderUnavailable(f"Payment provider '{name}' is not configured.")


def provider_for(org: Organization) -> str:
    """India → Razorpay; everywhere else → Stripe; mock when the real one isn't configured (dev)."""
    preferred = "razorpay" if org.country == "IN" else "stripe"
    try:
        get_payment_provider(preferred)
        return preferred
    except ProviderUnavailable:
        if settings.BILLING_ALLOW_MOCK:
            return "mock"
        raise
