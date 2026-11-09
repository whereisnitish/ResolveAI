from __future__ import annotations

from typing import Any
from zoneinfo import available_timezones

from rest_framework import serializers

from apps.accounts.models import User
from apps.organizations.serializers import MemberUserSerializer
from apps.workspaces.models import Workspace, WorkspaceMembership
from common.rbac import WorkspaceRole

_TIMEZONES = sorted(available_timezones())


class WorkspaceSerializer(serializers.ModelSerializer):
    role = serializers.SerializerMethodField()

    class Meta:
        model = Workspace
        fields = ["id", "organization", "name", "slug", "public_id", "timezone", "is_default", "role", "created_at"]
        read_only_fields = fields

    def get_role(self, obj: Workspace) -> str | None:
        roles: dict[Any, str] = self.context.get("roles", {})
        return roles.get(obj.id)


class WorkspaceCreateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=120)
    timezone = serializers.ChoiceField(choices=_TIMEZONES, default="UTC")


class WorkspaceUpdateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=120, required=False)
    timezone = serializers.ChoiceField(choices=_TIMEZONES, required=False)


class WorkspaceMembershipSerializer(serializers.ModelSerializer):
    user = MemberUserSerializer(read_only=True)

    class Meta:
        model = WorkspaceMembership
        fields = ["id", "user", "role", "is_active", "created_at"]
        read_only_fields = fields


class WorkspaceMemberCreateSerializer(serializers.Serializer):
    user_id = serializers.UUIDField()
    role = serializers.ChoiceField(choices=WorkspaceRole.choices, default=WorkspaceRole.AGENT)

    def validate_user_id(self, value: Any) -> User:
        # Restrict to users in the same organization; anything else looks
        # identical to a non-existent user (no cross-tenant user probing).
        workspace: Workspace = self.context["workspace"]
        user = User.objects.filter(
            id=value,
            is_active=True,
            organization_memberships__organization_id=workspace.organization_id,
            organization_memberships__is_active=True,
        ).first()
        if user is None:
            raise serializers.ValidationError("User not found in this organization.")
        return user


class WorkspaceMemberUpdateSerializer(serializers.Serializer):
    role = serializers.ChoiceField(choices=WorkspaceRole.choices, required=False)
    is_active = serializers.BooleanField(required=False)
