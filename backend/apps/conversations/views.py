from __future__ import annotations

import uuid
from typing import Any

from django.conf import settings
from django.db.models import Count, Exists, F, OuterRef, Q, QuerySet, Subquery
from django.http import FileResponse
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.pagination import CursorPagination
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import User
from apps.conversations import services
from apps.conversations.models import (
    Attachment,
    Channel,
    Conversation,
    ConversationReadState,
    ConversationStatus,
    Message,
)
from apps.conversations.serializers import (
    AssigneeSerializer,
    AssignSerializer,
    ConversationCountsSerializer,
    ConversationCreateSerializer,
    ConversationEventSerializer,
    ConversationSerializer,
    ConversationUpdateSerializer,
    MessageCreateSerializer,
    MessageSerializer,
)
from apps.customers.models import Customer
from apps.tenancy.access import workspace_users
from apps.tenancy.views import WorkspaceScopedViewMixin
from apps.workspaces.models import Team
from common.exceptions import ServiceError
from common.files import is_inline_safe, validate_upload
from common.rbac import Perm
from common.text import parse_uuid

OPEN_STATUSES = [ConversationStatus.OPEN, ConversationStatus.PENDING]


class MessageCursorPagination(CursorPagination):
    page_size = 50
    max_page_size = 100
    page_size_query_param = "page_size"
    ordering = "-created_at"


class ConversationViewSet(WorkspaceScopedViewMixin, viewsets.GenericViewSet):
    serializer_class = ConversationSerializer
    lookup_value_converter = "uuid"
    parser_classes = [JSONParser, MultiPartParser, FormParser]
    permission_by_action = {
        "list": Perm.CONVERSATIONS_VIEW,
        "retrieve": Perm.CONVERSATIONS_VIEW,
        "counts": Perm.CONVERSATIONS_VIEW,
        "events": Perm.CONVERSATIONS_VIEW,
        "read": Perm.CONVERSATIONS_VIEW,
        "messages": Perm.CONVERSATIONS_VIEW,  # POST additionally requires CONVERSATIONS_REPLY
        "create": Perm.CONVERSATIONS_REPLY,
        "partial_update": Perm.CONVERSATIONS_REPLY,
        "assign": Perm.CONVERSATIONS_ASSIGN,
    }

    def _base_queryset(self) -> QuerySet[Conversation]:
        my_read = ConversationReadState.objects.filter(conversation=OuterRef("pk"), user=self.request.user)
        return (
            Conversation.objects.filter(workspace=self.workspace)
            .select_related("customer", "assignee", "team")
            .prefetch_related("tags")
            .annotate(my_last_read_at=Subquery(my_read.values("last_read_at")[:1]))
        )

    def get_queryset(self) -> QuerySet[Conversation]:
        qs = self._base_queryset()
        if self.action != "list":
            return qs
        p = self.request.query_params
        status_param = p.get("status", "open")
        if status_param == "active":
            qs = qs.filter(status__in=OPEN_STATUSES)
        elif status_param in ConversationStatus.values:
            qs = qs.filter(status=status_param)
        elif status_param != "all":
            qs = qs.none()

        assignee = p.get("assignee")
        if assignee == "me":
            qs = qs.filter(assignee=self.request.user)
        elif assignee == "unassigned":
            qs = qs.filter(assignee__isnull=True)
        elif assignee:
            qs = qs.filter(assignee_id=parse_uuid(assignee)) if parse_uuid(assignee) else qs.none()

        for param, field in (("team", "team_id"), ("customer", "customer_id"), ("tag", "tags__id")):
            if value := p.get(param):
                qs = qs.filter(**{field: parse_uuid(value)}) if parse_uuid(value) else qs.none()
        if priority := p.get("priority"):
            qs = qs.filter(priority=priority)
        if p.get("unread") == "true":
            qs = qs.filter(last_customer_message_at__isnull=False).filter(
                Q(my_last_read_at__isnull=True) | Q(last_customer_message_at__gt=F("my_last_read_at"))
            )
        if q := p.get("q", "").strip()[:200]:
            matching_messages = Message.objects.filter(conversation=OuterRef("pk"), body__icontains=q)
            number_match = Q(number=int(q.lstrip("#"))) if q.lstrip("#").isdigit() else Q()
            qs = qs.filter(
                number_match
                | Q(subject__icontains=q)
                | Q(customer__name__icontains=q)
                | Q(customer__email__icontains=q)
                | Q(Exists(matching_messages))
            )
        ordering = "last_message_at" if p.get("ordering") == "oldest" else "-last_message_at"
        return qs.distinct().order_by(ordering)

    @extend_schema(
        parameters=[
            OpenApiParameter("status", str, enum=["open", "pending", "resolved", "closed", "active", "all"]),
            OpenApiParameter("assignee", str, description="'me', 'unassigned' or a user id"),
            OpenApiParameter("team", str),
            OpenApiParameter("customer", str),
            OpenApiParameter("tag", str),
            OpenApiParameter("priority", str),
            OpenApiParameter("unread", bool),
            OpenApiParameter("q", str, description="Search number, subject, customer, message text"),
            OpenApiParameter("ordering", str, enum=["newest", "oldest"]),
        ]
    )
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        page = self.paginate_queryset(self.get_queryset())
        return self.get_paginated_response(ConversationSerializer(page, many=True).data)

    def retrieve(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return Response(ConversationSerializer(self.get_object()).data)

    @extend_schema(request=ConversationCreateSerializer, responses={201: ConversationSerializer})
    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = ConversationCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        customer = get_object_or_404(Customer, id=data["customer_id"], workspace=self.workspace)
        conversation, _ = services.start_conversation(
            workspace=self.workspace,
            customer=customer,
            actor=services.Actor.agent(request.user),
            body=data["body"],
            subject=data.get("subject", ""),
            channel=Channel.DASHBOARD,
        )
        return Response(
            ConversationSerializer(self._base_queryset().get(pk=conversation.pk)).data, status=status.HTTP_201_CREATED
        )

    @extend_schema(request=ConversationUpdateSerializer, responses={200: ConversationSerializer})
    def partial_update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        conversation = self.get_object()
        serializer = ConversationUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.update_conversation(
            conversation=conversation, data=serializer.validated_data, actor=services.Actor.agent(request.user)
        )
        return Response(ConversationSerializer(self._base_queryset().get(pk=conversation.pk)).data)

    @extend_schema(request=AssignSerializer, responses={200: ConversationSerializer})
    @action(detail=True, methods=["post"])
    def assign(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        conversation = self.get_object()
        serializer = AssignSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        kwargs_: dict[str, Any] = {}
        if "assignee_id" in data:
            kwargs_["assignee"] = (
                None
                if data["assignee_id"] is None
                else User.objects.filter(id=data["assignee_id"], is_active=True).first()
            )
            if data["assignee_id"] is not None and kwargs_["assignee"] is None:
                raise ServiceError(
                    "That person can't be assigned conversations in this workspace.", code="invalid_assignee"
                )
        if "team_id" in data:
            kwargs_["team"] = (
                None
                if data["team_id"] is None
                else Team.objects.filter(id=data["team_id"], workspace=self.workspace).first()
            )
            if data["team_id"] is not None and kwargs_["team"] is None:
                raise ServiceError("Team not found.", code="invalid_team")
        services.assign_conversation(conversation=conversation, actor=services.Actor.agent(request.user), **kwargs_)
        return Response(ConversationSerializer(self._base_queryset().get(pk=conversation.pk)).data)

    @extend_schema(request=None, responses={204: None})
    @action(detail=True, methods=["post"])
    def read(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        services.mark_read(conversation=self.get_object(), user=request.user)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(methods=["GET"], responses={200: MessageSerializer(many=True)})
    @extend_schema(
        methods=["POST"],
        request={"multipart/form-data": MessageCreateSerializer, "application/json": MessageCreateSerializer},
        responses={201: MessageSerializer},
    )
    @action(detail=True, methods=["get", "post"])
    def messages(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        conversation = self.get_object()
        if request.method == "POST":
            if not self.get_workspace_access().has(Perm.CONVERSATIONS_REPLY):
                raise ServiceError("You do not have permission to reply.", code="permission_denied", status_code=403)
            serializer = MessageCreateSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            uploads = request.FILES.getlist("files")
            if len(uploads) > settings.ATTACHMENT_MAX_FILES:
                raise ValidationError({"files": [f"At most {settings.ATTACHMENT_MAX_FILES} files per message."]})
            files = [validate_upload(f) for f in uploads]
            message = services.post_message(
                conversation=conversation,
                actor=services.Actor.agent(request.user),
                body=serializer.validated_data.get("body", ""),
                kind=serializer.validated_data["kind"],
                files=files,
            )
            message = (
                Message.objects.select_related("author_user", "author_customer")
                .prefetch_related("attachments")
                .get(pk=message.pk)
            )
            return Response(MessageSerializer(message).data, status=status.HTTP_201_CREATED)

        qs = (
            conversation.messages.select_related("author_user", "author_customer")
            .prefetch_related("attachments")
            .order_by("-created_at")
        )
        paginator = MessageCursorPagination()
        page = paginator.paginate_queryset(qs, request, view=self)
        return paginator.get_paginated_response(MessageSerializer(page, many=True).data)

    @extend_schema(responses={200: ConversationEventSerializer(many=True)})
    @action(detail=True, methods=["get"])
    def events(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        events = self.get_object().events.select_related("actor_user").order_by("created_at")[:500]
        return Response(ConversationEventSerializer(events, many=True).data)

    @extend_schema(responses={200: ConversationCountsSerializer})
    @action(detail=False, methods=["get"])
    def counts(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        base = Conversation.objects.filter(workspace=self.workspace)
        active = base.filter(status__in=OPEN_STATUSES)
        agg = active.aggregate(
            mine=Count("id", filter=Q(assignee=request.user)),
            unassigned=Count("id", filter=Q(assignee__isnull=True)),
            all=Count("id"),
        )
        by_status = dict(base.values_list("status").annotate(n=Count("id")).values_list("status", "n"))
        by_team = {
            str(k): v
            for k, v in active.filter(team__isnull=False)
            .values_list("team_id")
            .annotate(n=Count("id"))
            .values_list("team_id", "n")
        }
        return Response(
            ConversationCountsSerializer(
                {**agg, "by_status": {s: by_status.get(s, 0) for s in ConversationStatus.values}, "by_team": by_team}
            ).data
        )


class AssigneeListView(WorkspaceScopedViewMixin, APIView):
    """People who can be assigned conversations in this workspace."""

    permission_by_action = {"get": Perm.CONVERSATIONS_VIEW}

    @extend_schema(responses={200: AssigneeSerializer(many=True)})
    def get(self, request: Request, workspace_id: uuid.UUID) -> Response:
        users = workspace_users(self.workspace, with_permission=Perm.CONVERSATIONS_REPLY).order_by("full_name", "email")
        data = [{"id": u.id, "full_name": u.get_full_name(), "email": u.email} for u in users]
        return Response(AssigneeSerializer(data, many=True).data)


class AttachmentDownloadView(WorkspaceScopedViewMixin, APIView):
    permission_by_action = {"get": Perm.CONVERSATIONS_VIEW}

    @extend_schema(responses={(200, "application/octet-stream"): bytes})
    def get(self, request: Request, workspace_id: uuid.UUID, attachment_id: uuid.UUID) -> FileResponse:
        attachment = get_object_or_404(Attachment, id=attachment_id, workspace=self.workspace, message__isnull=False)
        return attachment_response(attachment)


def attachment_response(attachment: Attachment) -> FileResponse:
    inline = is_inline_safe(attachment.content_type)
    response = FileResponse(
        attachment.file.open("rb"),
        as_attachment=not inline,
        filename=attachment.filename,
        content_type=attachment.content_type,
    )
    response["X-Content-Type-Options"] = "nosniff"
    response["Content-Security-Policy"] = "default-src 'none'; sandbox"
    response["Cache-Control"] = "private, max-age=300"
    return response
