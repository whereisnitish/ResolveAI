from __future__ import annotations

from typing import Any

from django.contrib.auth import password_validation
from rest_framework import serializers

from apps.accounts.models import User
from apps.organizations.models import OrganizationMembership
from apps.tenancy.access import accessible_workspaces
from apps.workspaces.models import WorkspaceMembership
from common.rbac import effective_workspace_role, org_permissions, workspace_permissions


class _PasswordField(serializers.CharField):
    def __init__(self, **kwargs: Any) -> None:
        kwargs.setdefault("write_only", True)
        kwargs.setdefault("trim_whitespace", False)
        kwargs.setdefault("max_length", 128)
        kwargs.setdefault("style", {"input_type": "password"})
        super().__init__(**kwargs)


class RegisterSerializer(serializers.Serializer):
    email = serializers.EmailField(max_length=254)
    password = _PasswordField()
    full_name = serializers.CharField(max_length=150)
    organization_name = serializers.CharField(max_length=120, required=False, allow_blank=True)
    country = serializers.RegexField(r"^[A-Za-z]{2}$", required=False, allow_blank=True)
    invitation_token = serializers.CharField(max_length=200, required=False, allow_blank=True)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if not attrs.get("invitation_token") and not (attrs.get("organization_name") or "").strip():
            raise serializers.ValidationError({"organization_name": "This field is required."})
        candidate = User(email=attrs["email"], full_name=attrs["full_name"])
        password_validation.validate_password(attrs["password"], user=candidate)
        return attrs


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField(max_length=254)
    password = _PasswordField()


class TokenSerializer(serializers.Serializer):
    token = serializers.CharField(max_length=500)


class EmailSerializer(serializers.Serializer):
    email = serializers.EmailField(max_length=254)


class PasswordResetConfirmSerializer(serializers.Serializer):
    uid = serializers.CharField(max_length=100)
    token = serializers.CharField(max_length=100)
    new_password = _PasswordField()

    def validate_new_password(self, value: str) -> str:
        password_validation.validate_password(value)
        return value


class PasswordChangeSerializer(serializers.Serializer):
    current_password = _PasswordField()
    new_password = _PasswordField()

    def validate_current_password(self, value: str) -> str:
        if not self.context["request"].user.check_password(value):
            raise serializers.ValidationError("Current password is incorrect.")
        return value

    def validate_new_password(self, value: str) -> str:
        password_validation.validate_password(value, user=self.context["request"].user)
        return value


class UserSerializer(serializers.ModelSerializer):
    email_verified = serializers.BooleanField(source="is_email_verified", read_only=True)

    class Meta:
        model = User
        fields = ["id", "email", "full_name", "email_verified", "date_joined"]
        read_only_fields = ["id", "email", "email_verified", "date_joined"]


class MeOrganizationSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()
    slug = serializers.CharField()
    role = serializers.CharField()
    permissions = serializers.ListField(child=serializers.CharField())


class MeWorkspaceSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    organization_id = serializers.UUIDField()
    name = serializers.CharField()
    slug = serializers.CharField()
    is_default = serializers.BooleanField()
    role = serializers.CharField()
    permissions = serializers.ListField(child=serializers.CharField())


class MeSerializer(serializers.Serializer):
    user = UserSerializer()
    organizations = MeOrganizationSerializer(many=True)
    workspaces = MeWorkspaceSerializer(many=True)


def build_me_payload(user: User) -> dict[str, Any]:
    """Everything the dashboard needs to render navigation and gate UI.

    The frontend uses `permissions` for UX only; the backend re-checks every request.
    """
    org_memberships = list(
        OrganizationMembership.objects.filter(user=user, is_active=True)
        .select_related("organization")
        .order_by("organization__name")
    )
    org_roles = {m.organization_id: m.role for m in org_memberships}
    ws_roles = dict(WorkspaceMembership.objects.filter(user=user, is_active=True).values_list("workspace_id", "role"))
    workspaces = []
    for ws in accessible_workspaces(user).order_by("organization__name", "-is_default", "name"):
        role = effective_workspace_role(org_roles[ws.organization_id], ws_roles.get(ws.id))
        if role is None:
            continue
        workspaces.append(
            {
                "id": ws.id,
                "organization_id": ws.organization_id,
                "name": ws.name,
                "slug": ws.slug,
                "is_default": ws.is_default,
                "role": role,
                "permissions": sorted(workspace_permissions(role)),
            }
        )
    return {
        "user": user,
        "organizations": [
            {
                "id": m.organization.id,
                "name": m.organization.name,
                "slug": m.organization.slug,
                "role": m.role,
                "permissions": sorted(org_permissions(m.role)),
            }
            for m in org_memberships
        ],
        "workspaces": workspaces,
    }
