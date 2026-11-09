from __future__ import annotations

import uuid
from typing import Any

from django.conf import settings
from django.http import FileResponse
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.conversations import services as conversation_services
from apps.conversations.models import Attachment, Channel, Conversation, Message, MessageKind
from apps.conversations.views import attachment_response
from apps.customers import services as customer_services
from apps.tenancy.views import WorkspaceScopedViewMixin
from apps.widget.auth import (
    IsWidgetVisitor,
    WidgetReadThrottle,
    WidgetSession,
    WidgetSessionThrottle,
    WidgetTokenAuthentication,
    WidgetWriteThrottle,
    get_widget_settings,
    issue_session_token,
)
from apps.widget.serializers import (
    IdentifySerializer,
    SessionRequestSerializer,
    SessionResponseSerializer,
    VisitorMessageSerializer,
    WidgetConversationSerializer,
    WidgetMessageSerializer,
    WidgetPublicSettingsSerializer,
    WidgetSettingsSerializer,
)
from apps.workspaces.models import Workspace
from common.rbac import Perm


def _visitor_payload(session_customer: Any) -> dict[str, Any]:
    return {"name": session_customer.name, "email": session_customer.email}


# -----------------------------------------------------------------------------
# Public widget API (website visitors)
# -----------------------------------------------------------------------------
class WidgetSessionView(APIView):
    """Exchange a workspace public id (+ optional visitor token) for a short-lived session."""

    authentication_classes: list = []
    permission_classes = [AllowAny]
    throttle_classes = [WidgetSessionThrottle]

    @extend_schema(request=SessionRequestSerializer, responses={200: SessionResponseSerializer}, auth=[])
    def post(self, request: Request) -> Response:
        serializer = SessionRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        workspace = (
            Workspace.objects.select_related("organization")
            .filter(public_id=data["workspace_id"], archived_at__isnull=True)
            .first()
        )
        widget_settings = get_widget_settings(workspace) if workspace else None
        if workspace is None or widget_settings is None or not widget_settings.enabled:
            raise NotFound("Chat is not available.", code="widget_unavailable")
        if not widget_settings.origin_allowed(request.headers.get("Origin")):
            raise PermissionDenied("This website is not allowed to use this chat widget.", code="origin_not_allowed")

        customer, identity, visitor_token = customer_services.get_or_create_visitor(
            workspace=workspace,
            raw_token=data.get("visitor_token") or None,
            page_url=data.get("page_url", ""),
            user_agent=request.headers.get("User-Agent", ""),
        )
        return Response(
            {
                "session_token": issue_session_token(identity),
                "expires_in": settings.WIDGET_SESSION_TTL_SECONDS,
                "visitor_token": visitor_token,
                "visitor": _visitor_payload(customer),
                "settings": WidgetPublicSettingsSerializer(widget_settings).data,
            }
        )


class _VisitorView(APIView):
    authentication_classes = [WidgetTokenAuthentication]
    permission_classes = [IsWidgetVisitor]

    def get_throttles(self) -> list[Any]:
        throttle = WidgetReadThrottle if self.request.method == "GET" else WidgetWriteThrottle
        return [throttle()]

    @property
    def session(self) -> WidgetSession:
        assert isinstance(self.request.auth, WidgetSession)
        return self.request.auth

    def own_conversation(self, conversation_id: uuid.UUID) -> Conversation:
        # Scoped to this visitor in this workspace: other visitors' ids 404.
        return get_object_or_404(
            Conversation, id=conversation_id, workspace=self.session.workspace, customer=self.session.customer
        )


class WidgetConversationsView(_VisitorView):
    @extend_schema(responses={200: WidgetConversationSerializer(many=True)})
    def get(self, request: Request) -> Response:
        qs = Conversation.objects.filter(workspace=self.session.workspace, customer=self.session.customer).order_by(
            "-last_message_at"
        )[:50]
        return Response(WidgetConversationSerializer(qs, many=True).data)

    @extend_schema(request=VisitorMessageSerializer, responses={201: WidgetConversationSerializer})
    def post(self, request: Request) -> Response:
        serializer = VisitorMessageSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        conversation, _ = conversation_services.start_conversation(
            workspace=self.session.workspace,
            customer=self.session.customer,
            actor=conversation_services.Actor.of_customer(self.session.customer),
            body=serializer.validated_data["body"],
            channel=Channel.WIDGET,
        )
        return Response(WidgetConversationSerializer(conversation).data, status=status.HTTP_201_CREATED)


class WidgetMessagesView(_VisitorView):
    @extend_schema(responses={200: WidgetMessageSerializer(many=True)})
    def get(self, request: Request, conversation_id: uuid.UUID) -> Response:
        conversation = self.own_conversation(conversation_id)
        messages = (
            Message.objects.filter(conversation=conversation, kind=MessageKind.REPLY)
            .select_related("author_user")
            .prefetch_related("attachments")
            .order_by("-created_at")[:200]
        )
        return Response([WidgetMessageSerializer(m).data for m in reversed(list(messages))])

    @extend_schema(request=VisitorMessageSerializer, responses={201: WidgetMessageSerializer})
    def post(self, request: Request, conversation_id: uuid.UUID) -> Response:
        conversation = self.own_conversation(conversation_id)
        serializer = VisitorMessageSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        message = conversation_services.post_message(
            conversation=conversation,
            actor=conversation_services.Actor.of_customer(self.session.customer),
            body=serializer.validated_data["body"],
        )
        return Response(WidgetMessageSerializer(message).data, status=status.HTTP_201_CREATED)


class WidgetIdentifyView(_VisitorView):
    @extend_schema(request=IdentifySerializer, responses={200: SessionResponseSerializer})
    def post(self, request: Request) -> Response:
        serializer = IdentifySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        customer = customer_services.identify_visitor(
            customer=self.session.customer,
            name=serializer.validated_data.get("name"),
            email=serializer.validated_data.get("email"),
        )
        return Response({"visitor": _visitor_payload(customer)})


class WidgetAttachmentView(_VisitorView):
    @extend_schema(responses={(200, "application/octet-stream"): bytes})
    def get(self, request: Request, attachment_id: uuid.UUID) -> FileResponse:
        attachment = get_object_or_404(
            Attachment,
            id=attachment_id,
            workspace=self.session.workspace,
            message__conversation__customer=self.session.customer,
            message__kind=MessageKind.REPLY,  # attachments on internal notes stay internal
        )
        return attachment_response(attachment)


# -----------------------------------------------------------------------------
# Dashboard: widget configuration
# -----------------------------------------------------------------------------
class WidgetSettingsView(WorkspaceScopedViewMixin, APIView):
    permission_by_action = {"get": Perm.WORKSPACE_VIEW, "patch": Perm.WORKSPACE_UPDATE}

    @extend_schema(responses={200: WidgetSettingsSerializer})
    def get(self, request: Request, workspace_id: uuid.UUID) -> Response:
        return Response(WidgetSettingsSerializer(get_widget_settings(self.workspace)).data)

    @extend_schema(request=WidgetSettingsSerializer, responses={200: WidgetSettingsSerializer})
    def patch(self, request: Request, workspace_id: uuid.UUID) -> Response:
        serializer = WidgetSettingsSerializer(get_widget_settings(self.workspace), data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        from apps.audit import services as audit

        audit.record(
            "workspace.widget_settings_updated",
            request=request,
            organization_id=self.workspace.organization_id,
            workspace_id=self.workspace.id,
            metadata={"fields": sorted(serializer.validated_data)},
        )
        return Response(serializer.data)
