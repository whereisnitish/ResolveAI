from __future__ import annotations

from typing import Any

from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from rest_framework.views import APIView

from apps.billing import services, usage
from apps.billing.models import Invoice, Plan
from apps.billing.providers import InvalidSignature, ProviderUnavailable, provider_for
from apps.tenancy.views import OrganizationScopedViewMixin
from common.exceptions import ServiceError
from common.rbac import Perm


class PlanSerializer(serializers.ModelSerializer):
    class Meta:
        model = Plan
        fields = ["code", "name", "description", "prices", "limits", "features", "trial_days"]
        read_only_fields = fields


class InvoiceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Invoice
        fields = [
            "id",
            "provider",
            "amount_minor",
            "currency",
            "status",
            "hosted_url",
            "period_start",
            "period_end",
            "issued_at",
        ]
        read_only_fields = fields


class CheckoutSerializer(serializers.Serializer):
    plan = serializers.SlugField()
    currency = serializers.ChoiceField(choices=["INR", "USD"])


class PlanListView(APIView):
    """Public pricing catalog."""

    permission_classes = [AllowAny]
    authentication_classes: list = []

    @extend_schema(responses={200: PlanSerializer(many=True)}, auth=[])
    def get(self, request: Request) -> Response:
        usage.ensure_catalog()
        return Response(PlanSerializer(Plan.objects.filter(is_public=True, is_trial=False), many=True).data)


class OrganizationBillingView(OrganizationScopedViewMixin, APIView):
    permission_by_action = {"get": Perm.ORG_BILLING_VIEW}

    @extend_schema(responses={200: dict})
    def get(self, request: Request, organization_id: Any) -> Response:
        org = self.organization
        sub = usage.ensure_subscription(org)
        try:
            provider = provider_for(org)
        except ProviderUnavailable:
            provider = None
        trial_days_left = (
            max(0, (sub.trial_ends_at - timezone.now()).days)
            if sub.trial_ends_at and sub.status == "trialing"
            else None
        )
        return Response(
            {
                "subscription": {
                    "plan": PlanSerializer(sub.plan).data,
                    "status": sub.status,
                    "is_active": usage.is_active(sub),
                    "provider": sub.provider,
                    "currency": sub.currency or ("INR" if org.country == "IN" else "USD"),
                    "trial_ends_at": sub.trial_ends_at,
                    "trial_days_left": trial_days_left,
                    "current_period_end": sub.current_period_end,
                    "cancel_at_period_end": sub.cancel_at_period_end,
                },
                "checkout_provider": provider,
                **usage.usage_summary(org),
            }
        )


class CheckoutView(OrganizationScopedViewMixin, APIView):
    permission_by_action = {"post": Perm.ORG_BILLING_MANAGE}

    @extend_schema(request=CheckoutSerializer, responses={200: dict})
    def post(self, request: Request, organization_id: Any) -> Response:
        serializer = CheckoutSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            session = services.start_checkout(
                org=self.organization,
                plan_code=serializer.validated_data["plan"],
                currency=serializer.validated_data["currency"],
                actor=request.user,
                request=request,
            )
        except ProviderUnavailable as exc:
            raise ServiceError(str(exc), code="billing_unavailable", status_code=503) from exc
        return Response({"provider": session.provider, "checkout_url": session.url})


class InvoiceListView(OrganizationScopedViewMixin, APIView):
    permission_by_action = {"get": Perm.ORG_BILLING_VIEW}

    @extend_schema(responses={200: InvoiceSerializer(many=True)})
    def get(self, request: Request, organization_id: Any) -> Response:
        return Response(InvoiceSerializer(Invoice.objects.filter(organization=self.organization)[:100], many=True).data)


class WebhookThrottle(AnonRateThrottle):
    rate = "600/min"


class BillingWebhookView(APIView):
    """POST /api/v1/billing/webhooks/{stripe|razorpay|mock}/ — signature-verified, idempotent."""

    permission_classes = [AllowAny]
    authentication_classes: list = []
    throttle_classes = [WebhookThrottle]

    @extend_schema(request=None, responses={200: dict}, auth=[])
    def post(self, request: Request, provider: str) -> Response:
        if provider not in ("stripe", "razorpay", "mock"):
            return Response(status=status.HTTP_404_NOT_FOUND)
        try:
            event, applied = services.process_webhook(provider, dict(request.headers), request.body)
        except ProviderUnavailable:
            return Response({"detail": "Provider not configured."}, status=status.HTTP_404_NOT_FOUND)
        except InvalidSignature:
            return Response({"detail": "Invalid signature."}, status=status.HTTP_400_BAD_REQUEST)
        if event.status == "failed":
            # 500 asks the provider to redeliver; the stored event will be retried.
            return Response({"status": "failed"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        return Response({"status": event.status, "duplicate": not applied})
