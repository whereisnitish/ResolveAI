"""Workspace catalog endpoints: tags and teams."""

from __future__ import annotations

import re
from typing import Any

from django.db import IntegrityError, transaction
from django.db.models import QuerySet
from rest_framework import serializers, status, viewsets
from rest_framework.request import Request
from rest_framework.response import Response

from apps.accounts.models import User
from apps.customers.serializers import TagSummarySerializer
from apps.tenancy.access import workspace_users
from apps.tenancy.views import WorkspaceScopedViewMixin
from apps.workspaces.models import Tag, Team
from common.exceptions import ConflictError
from common.rbac import Perm

HEX_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")


class TagWriteSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=50)
    color = serializers.RegexField(HEX_COLOR, required=False)

    def validate_name(self, value: str) -> str:
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Name is required.")
        return value


class TeamSerializer(serializers.ModelSerializer):
    members = serializers.SerializerMethodField()

    class Meta:
        model = Team
        fields = ["id", "name", "members", "created_at"]
        read_only_fields = fields

    def get_members(self, obj: Team) -> list[dict[str, Any]]:
        return [{"id": u.id, "full_name": u.get_full_name(), "email": u.email} for u in obj.members.all()]


class TeamWriteSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=80, required=False)
    member_ids = serializers.ListField(child=serializers.UUIDField(), required=False, max_length=500)


def _save_unique(fn: Any, label: str) -> Any:
    try:
        with transaction.atomic():
            return fn()
    except IntegrityError as exc:
        raise ConflictError(f"A {label} with this name already exists.", code="duplicate_name") from exc


class TagViewSet(WorkspaceScopedViewMixin, viewsets.GenericViewSet):
    lookup_value_converter = "uuid"
    serializer_class = TagSummarySerializer
    pagination_class = None
    permission_by_action = {
        "list": Perm.WORKSPACE_VIEW,
        "create": Perm.CONVERSATIONS_MANAGE,
        "partial_update": Perm.CONVERSATIONS_MANAGE,
        "destroy": Perm.CONVERSATIONS_MANAGE,
    }

    def get_queryset(self) -> QuerySet[Tag]:
        return Tag.objects.filter(workspace=self.workspace).order_by("name")

    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return Response(TagSummarySerializer(self.get_queryset(), many=True).data)

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        s = TagWriteSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        tag = _save_unique(lambda: Tag.objects.create(workspace=self.workspace, **s.validated_data), "tag")
        return Response(TagSummarySerializer(tag).data, status=status.HTTP_201_CREATED)

    def partial_update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        tag = self.get_object()
        s = TagWriteSerializer(data=request.data, partial=True)
        s.is_valid(raise_exception=True)
        for key, value in s.validated_data.items():
            setattr(tag, key, value)
        _save_unique(tag.save, "tag")
        return Response(TagSummarySerializer(tag).data)

    def destroy(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        self.get_object().delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class TeamViewSet(WorkspaceScopedViewMixin, viewsets.GenericViewSet):
    lookup_value_converter = "uuid"
    serializer_class = TeamSerializer
    pagination_class = None
    permission_by_action = {
        "list": Perm.WORKSPACE_VIEW,
        "create": Perm.WORKSPACE_MEMBERS_MANAGE,
        "partial_update": Perm.WORKSPACE_MEMBERS_MANAGE,
        "destroy": Perm.WORKSPACE_MEMBERS_MANAGE,
    }

    def get_queryset(self) -> QuerySet[Team]:
        return Team.objects.filter(workspace=self.workspace).prefetch_related("members").order_by("name")

    def _members(self, ids: list[Any]) -> list[User]:
        # Only people who can access this workspace may join its teams.
        users = list(workspace_users(self.workspace).filter(id__in=ids))
        if len(users) != len(set(ids)):
            raise serializers.ValidationError({"member_ids": ["One or more users are not members of this workspace."]})
        return users

    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return Response(TeamSerializer(self.get_queryset(), many=True).data)

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        s = TeamWriteSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        if not s.validated_data.get("name", "").strip():
            raise serializers.ValidationError({"name": ["Name is required."]})
        members = self._members(s.validated_data.get("member_ids", []))

        def _create() -> Team:
            team = Team.objects.create(workspace=self.workspace, name=s.validated_data["name"].strip())
            team.members.set(members)
            return team

        team = _save_unique(_create, "team")
        return Response(TeamSerializer(self.get_queryset().get(pk=team.pk)).data, status=status.HTTP_201_CREATED)

    def partial_update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        team = self.get_object()
        s = TeamWriteSerializer(data=request.data, partial=True)
        s.is_valid(raise_exception=True)
        if "name" in s.validated_data:
            team.name = s.validated_data["name"].strip()
            _save_unique(team.save, "team")
        if "member_ids" in s.validated_data:
            team.members.set(self._members(s.validated_data["member_ids"]))
        return Response(TeamSerializer(self.get_queryset().get(pk=team.pk)).data)

    def destroy(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        self.get_object().delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
