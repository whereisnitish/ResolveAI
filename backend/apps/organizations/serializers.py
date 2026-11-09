from __future__ import annotations

from typing import Any

from rest_framework import serializers

from apps.audit.models import AuditLog
from apps.organizations.models import Invitation, Organization, OrganizationMembership
from apps.workspaces.models import Workspace
from common.rbac import OrganizationRole, WorkspaceRole


class OrganizationSerializer(serializers.ModelSerializer):
    role = serializers.SerializerMethodField()

    class Meta:
        model = Organization
        fields = ["id", "name", "slug", "country", "role", "created_at"]
        read_only_fields = ["id", "slug", "role", "created_at"]

    def get_role(self, obj: Organization) -> str | None:
        roles: dict[Any, str] = self.context.get("roles", {})
        return roles.get(obj.id)


class OrganizationCreateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=120)
    country = serializers.RegexField(r"^[A-Za-z]{2}$", required=False, allow_blank=True)


class OrganizationUpdateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=120, required=False)
    country = serializers.RegexField(r"^[A-Za-z]{2}$", required=False, allow_blank=True)


class MemberUserSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    email = serializers.EmailField()
    full_name = serializers.CharField()


class OrganizationMembershipSerializer(serializers.ModelSerializer):
    user = MemberUserSerializer(read_only=True)

    class Meta:
        model = OrganizationMembership
        fields = ["id", "user", "role", "is_active", "created_at"]
        read_only_fields = fields


class OrganizationMembershipUpdateSerializer(serializers.Serializer):
    role = serializers.ChoiceField(choices=OrganizationRole.choices, required=False)
    is_active = serializers.BooleanField(required=False)


class InvitationSerializer(serializers.ModelSerializer):
    invited_by = MemberUserSerializer(read_only=True)
    is_expired = serializers.BooleanField(read_only=True)

    class Meta:
        model = Invitation
        fields = [
            "id",
            "email",
            "role",
            "workspace",
            "workspace_role",
            "status",
            "expires_at",
            "is_expired",
            "invited_by",
            "created_at",
        ]
        read_only_fields = fields


class InvitationCreateSerializer(serializers.Serializer):
    email = serializers.EmailField(max_length=254)
    role = serializers.ChoiceField(choices=OrganizationRole.choices, default=OrganizationRole.MEMBER)
    workspace = serializers.PrimaryKeyRelatedField(queryset=Workspace.objects.none(), required=False, allow_null=True)
    workspace_role = serializers.ChoiceField(choices=WorkspaceRole.choices, required=False, allow_blank=True)

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        organization: Organization | None = self.context.get("organization")
        if organization is not None:
            # Only workspaces of the caller's organization are valid choices;
            # foreign workspace IDs fail validation like non-existent ones.
            self.fields["workspace"].queryset = Workspace.objects.filter(
                organization=organization, archived_at__isnull=True
            )

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if attrs.get("workspace") and not attrs.get("workspace_role"):
            raise serializers.ValidationError({"workspace_role": "Required when a workspace is selected."})
        return attrs


class InvitationPreviewSerializer(serializers.Serializer):
    organization_name = serializers.CharField()
    email = serializers.EmailField()
    role = serializers.CharField()
    invited_by_name = serializers.CharField(allow_blank=True)
    expires_at = serializers.DateTimeField()
    account_exists = serializers.BooleanField()


class AuditLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = AuditLog
        fields = [
            "id",
            "action",
            "actor_email",
            "workspace_id",
            "target_type",
            "target_id",
            "metadata",
            "ip_address",
            "created_at",
        ]
        read_only_fields = fields
