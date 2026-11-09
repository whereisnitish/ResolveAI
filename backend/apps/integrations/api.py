from __future__ import annotations

from typing import Any

from django.db.models import QuerySet
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from apps.conversations.models import Conversation
from apps.integrations import services
from apps.integrations.models import SUPPORTED_EVENTS, Integration, IntegrationDelivery, IntegrationKind
from apps.tenancy.views import WorkspaceScopedViewMixin
from common.rbac import Perm
from common.safe_http import UnsafeURLError


class IntegrationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Integration
        fields = [
            "id",
            "kind",
            "name",
            "enabled",
            "url_host",
            "events",
            "consecutive_failures",
            "last_delivery_at",
            "created_at",
        ]
        read_only_fields = fields


class IntegrationCreateSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=IntegrationKind.choices)
    name = serializers.CharField(max_length=80)
    url = serializers.CharField(max_length=1000)
    events = serializers.ListField(child=serializers.ChoiceField(choices=SUPPORTED_EVENTS), min_length=1)


class IntegrationUpdateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=80, required=False)
    enabled = serializers.BooleanField(required=False)
    events = serializers.ListField(
        child=serializers.ChoiceField(choices=SUPPORTED_EVENTS), min_length=1, required=False
    )


class DeliverySerializer(serializers.ModelSerializer):
    class Meta:
        model = IntegrationDelivery
        fields = [
            "id",
            "event",
            "status",
            "attempts",
            "response_status",
            "error",
            "delivered_at",
            "created_at",
            "payload",
        ]
        read_only_fields = fields


class IntegrationViewSet(WorkspaceScopedViewMixin, viewsets.GenericViewSet):
    serializer_class = IntegrationSerializer
    lookup_value_converter = "uuid"
    pagination_class = None
    permission_by_action = {
        a: Perm.INTEGRATIONS_MANAGE
        for a in ("list", "retrieve", "create", "partial_update", "destroy", "deliveries", "test", "rotate_secret")
    }

    def get_queryset(self) -> QuerySet[Integration]:
        return Integration.objects.filter(workspace=self.workspace)

    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return Response(IntegrationSerializer(self.get_queryset(), many=True).data)

    def retrieve(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return Response(IntegrationSerializer(self.get_object()).data)

    @extend_schema(request=IntegrationCreateSerializer, responses={201: dict})
    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        s = IntegrationCreateSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        try:
            integration, secret = services.create_integration(
                workspace=self.workspace, user=request.user, **s.validated_data
            )
        except (UnsafeURLError, ValueError) as exc:
            raise serializers.ValidationError({"url": [str(exc)]}) from exc
        # The signing secret is returned exactly once.
        return Response(
            {**IntegrationSerializer(integration).data, "signing_secret": secret}, status=status.HTTP_201_CREATED
        )

    @extend_schema(request=IntegrationUpdateSerializer, responses={200: IntegrationSerializer})
    def partial_update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        integration = self.get_object()
        s = IntegrationUpdateSerializer(data=request.data, partial=True)
        s.is_valid(raise_exception=True)
        for k, v in s.validated_data.items():
            setattr(integration, k, v)
        if s.validated_data.get("enabled"):
            integration.consecutive_failures = 0
        integration.save()
        return Response(IntegrationSerializer(integration).data)

    def destroy(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        self.get_object().delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(responses={200: DeliverySerializer(many=True)})
    @action(detail=True, methods=["get"])
    def deliveries(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return Response(DeliverySerializer(self.get_object().deliveries.all()[:50], many=True).data)

    @extend_schema(request=None, responses={202: dict})
    @action(detail=True, methods=["post"])
    def test(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        integration = self.get_object()
        conv = Conversation.objects.filter(workspace=self.workspace).order_by("-created_at").first()
        if conv is None:
            raise serializers.ValidationError({"detail": ["Create a conversation first so there's something to send."]})
        services.fan_out("conversation.created", str(conv.id), test_integration=integration)
        return Response({"detail": "Test event queued."}, status=status.HTTP_202_ACCEPTED)

    @extend_schema(request=None, responses={200: dict})
    @action(detail=True, methods=["post"], url_path="rotate-secret")
    def rotate_secret(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        integration = self.get_object()
        if integration.kind != IntegrationKind.WEBHOOK:
            raise serializers.ValidationError({"detail": ["Only webhooks have signing secrets."]})
        return Response({"signing_secret": services.rotate_secret(integration)})
