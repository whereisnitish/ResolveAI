from __future__ import annotations

from typing import Any

from django.db import transaction
from django.http import HttpRequest

from apps.accounts.models import User
from apps.audit import services as audit
from apps.audit.services import AuditAction
from apps.organizations.models import Organization, OrganizationMembership
from apps.workspaces.models import Workspace, WorkspaceMembership
from common.exceptions import ConflictError, ServiceError
from common.rbac import WorkspaceRole
from common.text import unique_slug


@transaction.atomic
def create_workspace(
    *,
    organization: Organization,
    name: str,
    created_by: User | None,
    is_default: bool = False,
    timezone: str = "UTC",
    request: HttpRequest | None = None,
) -> Workspace:
    slug = unique_slug(
        name,
        lambda s: Workspace.objects.filter(organization=organization, slug=s).exists(),
        fallback="workspace",
    )
    workspace = Workspace.objects.create(
        organization=organization, name=name, slug=slug, is_default=is_default, timezone=timezone
    )
    # Creator gets an explicit admin membership so their access survives an
    # org role downgrade, and so they appear in workspace member lists.
    if created_by is not None:
        WorkspaceMembership.objects.create(workspace=workspace, user=created_by, role=WorkspaceRole.ADMIN)
    audit.record(
        AuditAction.WORKSPACE_CREATED,
        actor=created_by,
        request=request,
        organization_id=organization.id,
        workspace_id=workspace.id,
        target=workspace,
        metadata={"name": name},
    )
    return workspace


def update_workspace(
    *, workspace: Workspace, data: dict[str, Any], actor: User, request: HttpRequest | None
) -> Workspace:
    allowed = {"name", "timezone"}
    changed = {k: v for k, v in data.items() if k in allowed and getattr(workspace, k) != v}
    for key, value in changed.items():
        setattr(workspace, key, value)
    if changed:
        workspace.save(update_fields=[*changed.keys(), "updated_at"])
        audit.record(
            AuditAction.WORKSPACE_UPDATED,
            actor=actor,
            request=request,
            organization_id=workspace.organization_id,
            workspace_id=workspace.id,
            target=workspace,
            metadata={"fields": sorted(changed)},
        )
    return workspace


@transaction.atomic
def add_workspace_member(
    *, workspace: Workspace, user: User, role: str, actor: User, request: HttpRequest | None
) -> WorkspaceMembership:
    if not OrganizationMembership.objects.filter(
        organization_id=workspace.organization_id, user=user, is_active=True
    ).exists():
        raise ServiceError("User must be an active member of the organization first.", code="not_org_member")
    membership, created = WorkspaceMembership.objects.get_or_create(
        workspace=workspace, user=user, defaults={"role": role}
    )
    if not created:
        if membership.is_active:
            raise ConflictError("User is already a member of this workspace.", code="already_member")
        membership.is_active = True
        membership.role = role
        membership.save(update_fields=["is_active", "role", "updated_at"])
    audit.record(
        AuditAction.WORKSPACE_MEMBER_ADDED,
        actor=actor,
        request=request,
        organization_id=workspace.organization_id,
        workspace_id=workspace.id,
        target=membership,
        metadata={"user_id": str(user.id), "role": role},
    )
    return membership


def update_workspace_member(
    *, membership: WorkspaceMembership, data: dict[str, Any], actor: User, request: HttpRequest | None
) -> WorkspaceMembership:
    changed = {k: v for k, v in data.items() if k in {"role", "is_active"} and getattr(membership, k) != v}
    for key, value in changed.items():
        setattr(membership, key, value)
    if changed:
        membership.save(update_fields=[*changed.keys(), "updated_at"])
        audit.record(
            AuditAction.WORKSPACE_MEMBER_UPDATED,
            actor=actor,
            request=request,
            organization_id=membership.workspace.organization_id,
            workspace_id=membership.workspace_id,
            target=membership,
            metadata={k: v for k, v in changed.items()},
        )
    return membership


def remove_workspace_member(*, membership: WorkspaceMembership, actor: User, request: HttpRequest | None) -> None:
    audit.record(
        AuditAction.WORKSPACE_MEMBER_REMOVED,
        actor=actor,
        request=request,
        organization_id=membership.workspace.organization_id,
        workspace_id=membership.workspace_id,
        target=membership,
        metadata={"user_id": str(membership.user_id)},
    )
    membership.delete()
