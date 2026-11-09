from __future__ import annotations

from typing import Any

from django.db.models import Count, Q, QuerySet
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from apps.conversations.models import ConversationEvent
from apps.customers import services
from apps.customers.models import Customer, CustomerNote
from apps.customers.serializers import (
    CustomerNoteSerializer,
    CustomerSerializer,
    CustomerWriteSerializer,
    TimelineItemSerializer,
)
from apps.tenancy.views import WorkspaceScopedViewMixin
from common.exceptions import ServiceError
from common.rbac import Perm
from common.text import parse_uuid

EVENT_TITLES = {
    "created": "Started a conversation",
    "status_changed": "Conversation status changed",
    "priority_changed": "Priority changed",
    "assigned": "Conversation assigned",
    "team_assigned": "Conversation routed to team",
    "tags_changed": "Conversation tags updated",
    "reopened": "Reopened a conversation",
}


class CustomerViewSet(WorkspaceScopedViewMixin, viewsets.GenericViewSet):
    serializer_class = CustomerSerializer
    lookup_value_converter = "uuid"
    ordering_fields = ["created_at", "last_seen_at", "name"]
    permission_by_action = {
        "list": Perm.CUSTOMERS_VIEW,
        "retrieve": Perm.CUSTOMERS_VIEW,
        "create": Perm.CUSTOMERS_MANAGE,
        "partial_update": Perm.CUSTOMERS_MANAGE,
        "destroy": Perm.WORKSPACE_UPDATE,
        "notes": Perm.CUSTOMERS_VIEW,
        "timeline": Perm.CUSTOMERS_VIEW,
    }

    def get_queryset(self) -> QuerySet[Customer]:
        qs = (
            Customer.objects.filter(workspace=self.workspace)
            .prefetch_related("tags")
            .annotate(conversation_count=Count("conversations", distinct=True))
        )
        params = self.request.query_params
        if q := params.get("q", "").strip():
            qs = qs.filter(Q(name__icontains=q) | Q(email__icontains=q) | Q(phone__icontains=q))
        if tag := params.get("tag"):
            qs = qs.filter(tags__id=parse_uuid(tag)) if parse_uuid(tag) else qs.none()
        kind = params.get("type")
        if kind == "identified":
            qs = qs.filter(identified_at__isnull=False)
        elif kind == "anonymous":
            qs = qs.filter(identified_at__isnull=True)
        return qs.order_by(_ordering(params.get("ordering"), "-created_at", self.ordering_fields))

    @extend_schema(
        parameters=[
            OpenApiParameter("q", str, description="Search name, email or phone"),
            OpenApiParameter("tag", str),
            OpenApiParameter("type", str, enum=["identified", "anonymous"]),
        ]
    )
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        page = self.paginate_queryset(self.get_queryset())
        return self.get_paginated_response(CustomerSerializer(page, many=True).data)

    def retrieve(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return Response(CustomerSerializer(self.get_object()).data)

    @extend_schema(request=CustomerWriteSerializer, responses={201: CustomerSerializer})
    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = CustomerWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        customer = services.create_customer(workspace=self.workspace, data=serializer.validated_data)
        return Response(
            CustomerSerializer(self.get_queryset().get(pk=customer.pk)).data, status=status.HTTP_201_CREATED
        )

    @extend_schema(request=CustomerWriteSerializer, responses={200: CustomerSerializer})
    def partial_update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        customer = self.get_object()
        serializer = CustomerWriteSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        services.update_customer(customer=customer, data=serializer.validated_data)
        return Response(CustomerSerializer(self.get_queryset().get(pk=customer.pk)).data)

    def destroy(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        self.get_object().delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(methods=["GET"], responses={200: CustomerNoteSerializer(many=True)})
    @extend_schema(methods=["POST"], request=CustomerNoteSerializer, responses={201: CustomerNoteSerializer})
    @action(detail=True, methods=["get", "post"])
    def notes(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        customer = self.get_object()
        if request.method == "POST":
            if not self.get_workspace_access().has(Perm.CUSTOMERS_MANAGE):
                raise ServiceError(
                    "You do not have permission to add notes.", code="permission_denied", status_code=403
                )
            serializer = CustomerNoteSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            note = services.add_note(customer=customer, author=request.user, body=serializer.validated_data["body"])
            return Response(CustomerNoteSerializer(note).data, status=status.HTTP_201_CREATED)
        notes = customer.notes.select_related("author")[:200]
        return Response(CustomerNoteSerializer(notes, many=True).data)

    @extend_schema(responses={200: TimelineItemSerializer(many=True)})
    @action(detail=True, methods=["get"])
    def timeline(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        customer = self.get_object()
        items: list[dict[str, Any]] = [
            {
                "id": f"customer-{customer.id}",
                "kind": "customer_created",
                "title": "First seen" if customer.is_anonymous else "Customer created",
                "detail": customer.last_seen_url,
                "conversation_id": None,
                "actor_name": "",
                "at": customer.created_at,
            }
        ]
        events = (
            ConversationEvent.objects.filter(workspace=self.workspace, conversation__customer=customer)
            .select_related("actor_user", "conversation")
            .order_by("-created_at")[:100]
        )
        for e in events:
            items.append(
                {
                    "id": str(e.id),
                    "kind": f"conversation.{e.type}",
                    "title": EVENT_TITLES.get(e.type, e.type),
                    "detail": f"#{e.conversation.number} {_event_detail(e)}".strip(),
                    "conversation_id": e.conversation_id,
                    "actor_name": e.actor_user.get_full_name() if e.actor_user else "",
                    "at": e.created_at,
                }
            )
        for note in customer.notes.select_related("author")[:50]:
            items.append(
                {
                    "id": str(note.id),
                    "kind": "note",
                    "title": "Note added",
                    "detail": note.body[:200],
                    "conversation_id": None,
                    "actor_name": note.author.get_full_name() if note.author else "",
                    "at": note.created_at,
                }
            )
        items.sort(key=lambda i: i["at"], reverse=True)
        return Response(TimelineItemSerializer(items[:150], many=True).data)


class CustomerNoteDetailViewSet(WorkspaceScopedViewMixin, viewsets.GenericViewSet):
    serializer_class = CustomerNoteSerializer
    lookup_value_converter = "uuid"
    permission_by_action = {"destroy": Perm.CUSTOMERS_MANAGE}

    def destroy(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        note = get_object_or_404(CustomerNote, id=kwargs["pk"], workspace=self.workspace)
        is_author = note.author_id == request.user.id
        if not is_author and not self.get_workspace_access().has(Perm.WORKSPACE_UPDATE):
            raise ServiceError(
                "Only the author or a workspace admin can delete this note.", code="permission_denied", status_code=403
            )
        note.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


def _event_detail(event: ConversationEvent) -> str:
    data = event.data or {}
    if event.type == "status_changed":
        return f"{data.get('from')} → {data.get('to')}"
    if event.type == "priority_changed":
        return f"{data.get('from')} → {data.get('to')}"
    if event.type == "assigned":
        return f"to {data.get('assignee_name') or 'nobody'}"
    if event.type == "team_assigned":
        return f"to {data.get('team_name') or 'no team'}"
    return ""


def _ordering(requested: str | None, default: str, allowed: list[str]) -> str:
    if requested and requested.lstrip("-") in allowed:
        return requested
    return default
