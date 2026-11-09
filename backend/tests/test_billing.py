from __future__ import annotations

import hashlib
import hmac
import json
import time

import httpx
import pytest
from django.db import IntegrityError, transaction

from apps.billing import usage
from apps.billing.models import Invoice, Metric, Subscription, UsageLedger, WebhookEvent
from apps.billing.providers import RazorpayProvider, StripeProvider
from apps.organizations.models import Organization
from tests.factories import OrganizationMembershipFactory
from tests.helpers import set_plan

STRIPE_SECRET = "whsec_test_stripe"
RZP_SECRET = "rzp_whsec_test"


def stripe_post(api_client, payload: dict, secret: str = STRIPE_SECRET, ts: int | None = None):  # type: ignore[no-untyped-def]
    body = json.dumps(payload).encode()
    ts = ts or int(time.time())
    sig = hmac.new(secret.encode(), f"{ts}.".encode() + body, hashlib.sha256).hexdigest()
    return api_client.post(
        "/api/v1/billing/webhooks/stripe/",
        body,
        content_type="application/json",
        HTTP_STRIPE_SIGNATURE=f"t={ts},v1={sig}",
    )


def rzp_post(api_client, payload: dict, event_id: str, secret: str = RZP_SECRET):  # type: ignore[no-untyped-def]
    body = json.dumps(payload).encode()
    sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return api_client.post(
        "/api/v1/billing/webhooks/razorpay/",
        body,
        content_type="application/json",
        HTTP_X_RAZORPAY_SIGNATURE=sig,
        HTTP_X_RAZORPAY_EVENT_ID=event_id,
    )


def checkout_completed(org: Organization, event_id: str = "evt_1") -> dict:
    return {
        "id": event_id,
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "mode": "subscription",
                "client_reference_id": str(org.id),
                "metadata": {"org_id": str(org.id), "plan": "growth"},
                "customer": "cus_123",
                "subscription": "sub_123",
                "currency": "usd",
            }
        },
    }


def invoice_paid(event_id: str = "evt_inv", invoice_id: str = "in_1", kind: str = "invoice.paid") -> dict:
    return {
        "id": event_id,
        "type": kind,
        "data": {
            "object": {
                "id": invoice_id,
                "customer": "cus_123",
                "subscription": "sub_123",
                "amount_paid": 9900,
                "amount_due": 9900,
                "currency": "usd",
                "hosted_invoice_url": "https://invoice.stripe.com/i/1",
                "created": int(time.time()),
            }
        },
    }


class TestSubscriptionsAndPlans:
    def test_registration_starts_trial(self, api_client):
        r = api_client.post(
            "/api/v1/auth/register/",
            {"email": "f@x.com", "password": "a-Very-strong-passw0rd", "full_name": "F", "organization_name": "F Co"},
            format="json",
        )
        assert r.status_code == 201
        sub = Subscription.objects.get(organization__name="F Co")
        assert sub.status == "trialing" and sub.plan.code == "trial" and sub.trial_ends_at

    def test_public_plans_exclude_trial(self, api_client):
        codes = [p["code"] for p in api_client.get("/api/v1/billing/plans/").json()]
        assert codes == ["starter", "growth", "scale"]

    def test_billing_overview_permissions(self, client_for, tenant_a, tenant_b):
        url = f"/api/v1/organizations/{tenant_a.org.id}/billing/"
        assert client_for(tenant_a.billing_admin).get(url).status_code == 200
        assert client_for(tenant_a.member).get(url).status_code == 403
        assert client_for(tenant_b.owner).get(url).status_code == 404
        body = client_for(tenant_a.owner).get(url).json()
        assert body["subscription"]["plan"]["code"] == "scale" and body["usage"]["seats"] == 6

    def test_expired_trial_pauses_ai_but_not_inbox(self, tenant_a):
        from django.utils import timezone

        sub = set_plan(tenant_a.org, "trial", status="trialing")
        sub.trial_ends_at = timezone.now() - timezone.timedelta(days=1)
        sub.save()
        assert usage.effective_limits(tenant_a.org)["ai_executions_per_month"] == 0
        assert not usage.ai_quota_available(tenant_a.org)


class TestCheckout:
    def test_mock_checkout_activates_via_signed_webhook_pipeline(self, client_for, tenant_a, settings):
        settings.STRIPE_SECRET_KEY = ""  # no real provider → mock (dev)
        r = client_for(tenant_a.owner).post(
            f"/api/v1/organizations/{tenant_a.org.id}/billing/checkout/",
            {"plan": "growth", "currency": "USD"},
            format="json",
        )
        assert r.status_code == 200 and r.json()["provider"] == "mock"
        sub = Subscription.objects.get(organization=tenant_a.org)
        assert sub.plan.code == "growth" and sub.status == "active" and sub.provider == "mock"
        assert Invoice.objects.get(organization=tenant_a.org).amount_minor == 9900
        assert WebhookEvent.objects.get(provider="mock").status == "processed"

    def test_checkout_permissions_and_validation(self, client_for, tenant_a):
        url = f"/api/v1/organizations/{tenant_a.org.id}/billing/checkout/"
        assert (
            client_for(tenant_a.admin).post(url, {"plan": "growth", "currency": "USD"}, format="json").status_code
            == 403
        )
        owner = client_for(tenant_a.owner)
        assert (
            owner.post(url, {"plan": "trial", "currency": "USD"}, format="json").json()["error"]["code"]
            == "invalid_plan"
        )
        assert owner.post(url, {"plan": "growth", "currency": "EUR"}, format="json").status_code == 400

    def test_stripe_checkout_request(self, tenant_a, settings):
        from apps.billing.models import Plan

        seen = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["url"], seen["body"], seen["auth"] = (
                str(request.url),
                request.content.decode(),
                request.headers["authorization"],
            )
            return httpx.Response(200, json={"id": "cs_1", "url": "https://checkout.stripe.com/c/cs_1"})

        provider = StripeProvider("sk_test_x", STRIPE_SECRET, transport=httpx.MockTransport(handler))
        session = provider.create_checkout(
            org=tenant_a.org,
            plan=Plan.objects.get(code="growth"),
            currency="USD",
            success_url="https://a/s",
            cancel_url="https://a/c",
        )
        assert session.url == "https://checkout.stripe.com/c/cs_1"
        assert seen["url"].endswith("/v1/checkout/sessions")
        assert "mode=subscription" in seen["body"] and "unit_amount%5D=9900" in seen["body"]
        assert f"client_reference_id={tenant_a.org.id}" in seen["body"]

    def test_razorpay_requires_configured_plan(self, tenant_a):
        from apps.billing.models import Plan
        from apps.billing.providers import ProviderUnavailable

        provider = RazorpayProvider("k", "s", RZP_SECRET, transport=httpx.MockTransport(lambda r: httpx.Response(500)))
        with pytest.raises(ProviderUnavailable):
            provider.create_checkout(
                org=tenant_a.org, plan=Plan.objects.get(code="growth"), currency="INR", success_url="", cancel_url=""
            )


class TestWebhooks:
    def test_stripe_activation_and_invoice(self, api_client, tenant_a):
        assert stripe_post(api_client, checkout_completed(tenant_a.org)).json() == {
            "status": "processed",
            "duplicate": False,
        }
        sub = Subscription.objects.get(organization=tenant_a.org)
        assert sub.plan.code == "growth" and sub.provider == "stripe" and sub.provider_subscription_id == "sub_123"
        stripe_post(api_client, invoice_paid())
        assert Invoice.objects.get(provider_invoice_id="in_1").status == "paid"

    def test_duplicate_webhook_processed_once(self, api_client, tenant_a):
        """Critical security test #6."""
        stripe_post(api_client, checkout_completed(tenant_a.org))
        first = stripe_post(api_client, invoice_paid())
        again = stripe_post(api_client, invoice_paid())
        assert first.json()["duplicate"] is False and again.json() == {"status": "processed", "duplicate": True}
        assert Invoice.objects.count() == 1
        event = WebhookEvent.objects.get(event_id="evt_inv")
        assert event.attempts == 1

    def test_razorpay_signature_and_dedupe(self, api_client, tenant_b):
        tenant_b.org.country = "IN"
        tenant_b.org.save()
        payload = {
            "event": "subscription.charged",
            "payload": {
                "subscription": {
                    "entity": {
                        "id": "sub_rzp_1",
                        "customer_id": "cust_1",
                        "current_start": int(time.time()),
                        "current_end": int(time.time()) + 2_592_000,
                        "notes": {"org_id": str(tenant_b.org.id), "plan": "starter"},
                    }
                },
                "payment": {
                    "entity": {"id": "pay_1", "amount": 249900, "currency": "INR", "created_at": int(time.time())}
                },
            },
        }
        assert rzp_post(api_client, payload, "evt_rzp_1").status_code == 200
        assert rzp_post(api_client, payload, "evt_rzp_1").json()["duplicate"] is True
        sub = Subscription.objects.get(organization=tenant_b.org)
        assert (sub.plan.code, sub.status, sub.provider, sub.currency) == ("starter", "active", "razorpay", "INR")
        assert Invoice.objects.filter(provider="razorpay").count() == 1
        assert rzp_post(api_client, payload, "evt_rzp_2", secret="wrong").status_code == 400

    @pytest.mark.parametrize("variant", ["bad_secret", "stale", "tampered"])
    def test_invalid_stripe_signatures_rejected(self, api_client, tenant_a, variant):
        payload = checkout_completed(tenant_a.org)
        if variant == "bad_secret":
            r = stripe_post(api_client, payload, secret="whsec_wrong")
        elif variant == "stale":
            r = stripe_post(api_client, payload, ts=int(time.time()) - 3600)
        else:
            body = json.dumps(payload).encode()
            ts = int(time.time())
            sig = hmac.new(STRIPE_SECRET.encode(), f"{ts}.".encode() + body, hashlib.sha256).hexdigest()
            payload["data"]["object"]["metadata"]["plan"] = "scale"
            r = api_client.post(
                "/api/v1/billing/webhooks/stripe/",
                json.dumps(payload),
                content_type="application/json",
                HTTP_STRIPE_SIGNATURE=f"t={ts},v1={sig}",
            )
        assert r.status_code == 400
        assert not WebhookEvent.objects.exists()
        assert Subscription.objects.get(organization=tenant_a.org).plan.code == "scale"  # unchanged fixture plan

    def test_failed_processing_is_retried_on_redelivery(self, api_client, tenant_a):
        payload = invoice_paid(event_id="evt_orphan", invoice_id="in_orphan")
        payload["data"]["object"]["subscription"] = "sub_unknown"
        assert stripe_post(api_client, payload).status_code == 500
        assert WebhookEvent.objects.get(event_id="evt_orphan").status == "failed"
        Subscription.objects.filter(organization=tenant_a.org).update(
            provider="stripe", provider_subscription_id="sub_unknown"
        )
        assert stripe_post(api_client, payload).json()["status"] == "processed"
        assert WebhookEvent.objects.get(event_id="evt_orphan").attempts == 2

    def test_payment_failure_marks_past_due(self, api_client, tenant_a):
        stripe_post(api_client, checkout_completed(tenant_a.org))
        stripe_post(api_client, invoice_paid(event_id="evt_fail", invoice_id="in_f", kind="invoice.payment_failed"))
        assert Subscription.objects.get(organization=tenant_a.org).status == "past_due"

    def test_unknown_provider_and_unconfigured(self, api_client, settings):
        assert api_client.post("/api/v1/billing/webhooks/paypal/", {}, format="json").status_code == 404
        settings.STRIPE_WEBHOOK_SECRET = ""
        assert api_client.post("/api/v1/billing/webhooks/stripe/", {}, format="json").status_code == 404


class TestUsageAndLimits:
    def test_ledger_is_append_only_and_idempotent(self, tenant_a):
        assert usage.record_usage(
            organization_id=tenant_a.org.id, metric=Metric.AI_EXECUTIONS, quantity=1, idempotency_key="k1"
        )
        assert not usage.record_usage(
            organization_id=tenant_a.org.id, metric=Metric.AI_EXECUTIONS, quantity=1, idempotency_key="k1"
        )
        entry = UsageLedger.objects.get()
        with pytest.raises(RuntimeError):
            entry.save()
        with pytest.raises(RuntimeError):
            entry.delete()
        with pytest.raises(ValueError):
            usage.record_usage(
                organization_id=tenant_a.org.id, metric=Metric.AI_EXECUTIONS, quantity=-5, idempotency_key="k2"
            )
        with pytest.raises(IntegrityError), transaction.atomic():
            UsageLedger.objects.create(
                organization=tenant_a.org,
                metric="ai_executions",
                quantity=-1,
                idempotency_key="k3",
                occurred_at=entry.occurred_at,
            )

    def test_ai_quota(self, tenant_a):
        set_plan(tenant_a.org, "starter", ai_executions_per_month=2)
        for i in range(2):
            assert usage.ai_quota_available(tenant_a.org)
            usage.record_usage(
                organization_id=tenant_a.org.id, metric=Metric.AI_EXECUTIONS, quantity=1, idempotency_key=f"q{i}"
            )
        assert not usage.ai_quota_available(tenant_a.org)

    def test_seat_limit_blocks_invitations(self, client_for, tenant_a):
        set_plan(tenant_a.org, "starter", seats=6)
        r = client_for(tenant_a.owner).post(
            f"/api/v1/organizations/{tenant_a.org.id}/invitations/",
            {"email": "n@x.com", "role": "member"},
            format="json",
        )
        assert r.status_code == 402 and r.json()["error"]["code"] == "plan_limit_reached"
        set_plan(tenant_a.org, "starter", seats=7)
        assert (
            client_for(tenant_a.owner)
            .post(
                f"/api/v1/organizations/{tenant_a.org.id}/invitations/",
                {"email": "n@x.com", "role": "member"},
                format="json",
            )
            .status_code
            == 201
        )

    def test_workspace_limit(self, client_for, tenant_a):
        set_plan(tenant_a.org, "starter", workspaces=1)
        r = client_for(tenant_a.owner).post(
            f"/api/v1/organizations/{tenant_a.org.id}/workspaces/", {"name": "Two"}, format="json"
        )
        assert r.status_code == 402

    def test_usage_summary_counts_server_side_only(self, client_for, tenant_a):
        OrganizationMembershipFactory(organization=tenant_a.org)
        usage.record_usage(
            organization_id=tenant_a.org.id, metric=Metric.AI_INPUT_TOKENS, quantity=1234, idempotency_key="t"
        )
        body = client_for(tenant_a.owner).get(f"/api/v1/organizations/{tenant_a.org.id}/billing/").json()
        assert body["usage"]["seats"] == 7 and body["usage"]["ai_input_tokens"] == 1234
        assert body["limits"]["seats"] == 50
