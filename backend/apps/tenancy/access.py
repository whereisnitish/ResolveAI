"""Resolve what a user may do in an organization or workspace.

All authorization decisions for tenant data flow through these functions.
They always start from the authenticated user and the database — never from
client-provided role or tenant claims.

Access requires, at every level:
  * an active user,
  * an active OrganizationMembership,
  * for workspaces: the workspace is not archived AND either the org role grants
    implicit workspace admin, or there is an active WorkspaceMembership.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from django.contrib.auth.models import AnonymousUser
from django.db.models import Exists, OuterRef, Q, QuerySet

from apps.accounts.models import User
from apps.organizations.models import Organization, OrganizationMembership
from apps.workspaces.models import Workspace, WorkspaceMembership
from common.rbac import (
    ORG_ROLES_WITH_IMPLICIT_WORKSPACE_ADMIN,
    effective_workspace_role,
    org_permissions,
    workspace_permissions,
    workspace_roles_with,
)


@dataclass(frozen=True)
class OrganizationAccess:
    organization: Organization
    membership: OrganizationMembership
    permissions: frozenset[str] = field(default_factory=frozenset)

    @property
    def role(self) -> str:
        return self.membership.role

    def has(self, perm: str) -> bool:
        return perm in self.permissions


@dataclass(frozen=True)
class WorkspaceAccess:
    workspace: Workspace
    org_access: OrganizationAccess
    workspace_membership: WorkspaceMembership | None
    role: str
    permissions: frozenset[str] = field(default_factory=frozenset)

    @property
    def organization(self) -> Organization:
        return self.org_access.organization

    def has(self, perm: str) -> bool:
        return perm in self.permissions


def _as_uuid(value: object) -> uuid.UUID | None:
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        return None


def _is_active_user(user: User | AnonymousUser | None) -> bool:
    return bool(user is not None and user.is_authenticated and user.is_active)


def get_organization_access(user: User | AnonymousUser | None, organization_id: object) -> OrganizationAccess | None:
    org_uuid = _as_uuid(organization_id)
    if org_uuid is None or not _is_active_user(user):
        return None
    membership = (
        OrganizationMembership.objects.select_related("organization")
        .filter(organization_id=org_uuid, user=user, is_active=True)
        .first()
    )
    if membership is None:
        return None
    return OrganizationAccess(
        organization=membership.organization,
        membership=membership,
        permissions=org_permissions(membership.role),
    )


def get_workspace_access(user: User | AnonymousUser | None, workspace_id: object) -> WorkspaceAccess | None:
    ws_uuid = _as_uuid(workspace_id)
    if ws_uuid is None or not _is_active_user(user):
        return None
    workspace = Workspace.objects.select_related("organization").filter(id=ws_uuid, archived_at__isnull=True).first()
    if workspace is None:
        return None
    org_access = get_organization_access(user, workspace.organization_id)
    if org_access is None:
        return None
    ws_membership = WorkspaceMembership.objects.filter(workspace=workspace, user=user, is_active=True).first()
    role = effective_workspace_role(org_access.role, ws_membership.role if ws_membership else None)
    if role is None:
        return None
    return WorkspaceAccess(
        workspace=workspace,
        org_access=org_access,
        workspace_membership=ws_membership,
        role=role,
        permissions=workspace_permissions(role),
    )


def accessible_organizations(user: User) -> QuerySet[Organization]:
    if not _is_active_user(user):
        return Organization.objects.none()
    return Organization.objects.filter(memberships__user=user, memberships__is_active=True).distinct()


def accessible_workspaces(user: User) -> QuerySet[Workspace]:
    """Every non-archived workspace the user can open, across all their orgs."""
    if not _is_active_user(user):
        return Workspace.objects.none()
    active_org_memberships = OrganizationMembership.objects.filter(
        organization_id=OuterRef("organization_id"), user=user, is_active=True
    )
    privileged_org_memberships = active_org_memberships.filter(role__in=ORG_ROLES_WITH_IMPLICIT_WORKSPACE_ADMIN)
    explicit_ws_memberships = WorkspaceMembership.objects.filter(workspace_id=OuterRef("pk"), user=user, is_active=True)
    return (
        Workspace.objects.filter(archived_at__isnull=True)
        .filter(Exists(active_org_memberships))
        .filter(Q(Exists(privileged_org_memberships)) | Q(Exists(explicit_ws_memberships)))
        .select_related("organization")
    )


def workspace_users(workspace: Workspace, with_permission: str | None = None) -> QuerySet[User]:
    """Active users who can currently open ``workspace`` (implicit org admins included).

    With ``with_permission``, only users whose effective workspace role grants it.
    Implemented in SQL (no per-user access resolution) so it scales with team size.
    """
    active_org_member = OrganizationMembership.objects.filter(
        organization_id=workspace.organization_id, user=OuterRef("pk"), is_active=True
    )
    privileged = active_org_member.filter(role__in=ORG_ROLES_WITH_IMPLICIT_WORKSPACE_ADMIN)
    explicit = WorkspaceMembership.objects.filter(workspace=workspace, user=OuterRef("pk"), is_active=True)
    if with_permission is not None:
        explicit = explicit.filter(role__in=workspace_roles_with(with_permission))
    return (
        User.objects.filter(is_active=True)
        .filter(Exists(active_org_member))
        .filter(Q(Exists(privileged)) | Q(Exists(explicit)))
    )


def user_has_workspace_permission(user: User, workspace: Workspace, perm: str) -> bool:
    access = get_workspace_access(user, workspace.id)
    return access is not None and access.has(perm)
