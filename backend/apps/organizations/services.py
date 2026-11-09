from __future__ import annotations

import hashlib
import secrets
from typing import Any

from django.conf import settings
from django.db import transaction
from django.http import HttpRequest
from django.utils import timezone

from apps.accounts.models import User, UserManager
from apps.audit import services as audit
from apps.audit.services import AuditAction
from apps.organizations.models import Invitation, InvitationStatus, Organization, OrganizationMembership
from apps.tenancy.access import OrganizationAccess
from apps.workspaces.models import Workspace, WorkspaceMembership
from apps.workspaces.services import create_workspace
from common.email import queue_email
from common.exceptions import ConflictError, ServiceError
from common.rbac import ASSIGNABLE_ORG_ROLES, OrganizationRole, Perm
from common.text import unique_slug

DEFAULT_WORKSPACE_NAME = "Support"


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


# -----------------------------------------------------------------------------
# Organizations
# -----------------------------------------------------------------------------
@transaction.atomic
def create_organization(
    *, name: str, owner: User, country: str = "", request: HttpRequest | None = None
) -> tuple[Organization, Workspace]:
    """Create an organization with ``owner`` as Owner plus a default workspace."""
    slug = unique_slug(name, lambda s: Organization.objects.filter(slug=s).exists(), fallback="org")
    org = Organization.objects.create(name=name, slug=slug, country=country.upper(), created_by=owner)
    OrganizationMembership.objects.create(organization=org, user=owner, role=OrganizationRole.OWNER)
    workspace = create_workspace(
        organization=org, name=DEFAULT_WORKSPACE_NAME, created_by=owner, is_default=True, request=request
    )
    from apps.billing.usage import ensure_subscription

    ensure_subscription(org)  # every new organization starts a free trial
    audit.record(
        AuditAction.ORG_CREATED,
        actor=owner,
        request=request,
        organization_id=org.id,
        target=org,
        metadata={"name": name},
    )
    return org, workspace


def update_organization(
    *, organization: Organization, data: dict[str, Any], actor: User, request: HttpRequest | None
) -> Organization:
    allowed = {"name", "country"}
    changed = {k: v for k, v in data.items() if k in allowed and getattr(organization, k) != v}
    if "country" in changed:
        changed["country"] = changed["country"].upper()
    for key, value in changed.items():
        setattr(organization, key, value)
    if changed:
        organization.save(update_fields=[*changed.keys(), "updated_at"])
        audit.record(
            AuditAction.ORG_UPDATED,
            actor=actor,
            request=request,
            organization_id=organization.id,
            target=organization,
            metadata={"fields": sorted(changed)},
        )
    return organization


# -----------------------------------------------------------------------------
# Membership management
# -----------------------------------------------------------------------------
def _assert_can_assign(actor_access: OrganizationAccess, role: str) -> None:
    if role not in ASSIGNABLE_ORG_ROLES.get(actor_access.role, frozenset()):
        raise ServiceError("You cannot assign this role.", code="role_not_assignable", status_code=403)


def _assert_can_manage_target(actor_access: OrganizationAccess, target: OrganizationMembership) -> None:
    if target.role == OrganizationRole.OWNER and not actor_access.has(Perm.ORG_OWNERSHIP_MANAGE):
        raise ServiceError("Only owners can modify another owner.", code="owner_protected", status_code=403)


def _assert_not_last_owner(membership: OrganizationMembership) -> None:
    """Lock owner rows and ensure at least one other active owner remains."""
    if membership.role != OrganizationRole.OWNER or not membership.is_active:
        return
    owners = list(
        OrganizationMembership.objects.select_for_update()
        .filter(organization_id=membership.organization_id, role=OrganizationRole.OWNER, is_active=True)
        .values_list("id", flat=True)
    )
    if [pk for pk in owners if pk != membership.id] == []:
        raise ConflictError("An organization must keep at least one active owner.", code="last_owner")


@transaction.atomic
def update_member(
    *,
    membership: OrganizationMembership,
    data: dict[str, Any],
    actor_access: OrganizationAccess,
    request: HttpRequest | None,
) -> OrganizationMembership:
    _assert_can_manage_target(actor_access, membership)
    changed = {k: v for k, v in data.items() if k in {"role", "is_active"} and getattr(membership, k) != v}
    if not changed:
        return membership
    if "role" in changed:
        _assert_can_assign(actor_access, changed["role"])
    if changed.get("role", OrganizationRole.OWNER) != OrganizationRole.OWNER or changed.get("is_active") is False:
        _assert_not_last_owner(membership)
    for key, value in changed.items():
        setattr(membership, key, value)
    membership.save(update_fields=[*changed.keys(), "updated_at"])
    audit.record(
        AuditAction.ORG_MEMBER_UPDATED,
        actor=actor_access.membership.user,
        request=request,
        organization_id=membership.organization_id,
        target=membership,
        metadata={"user_id": str(membership.user_id), **changed},
    )
    return membership


@transaction.atomic
def remove_member(
    *, membership: OrganizationMembership, actor_access: OrganizationAccess, request: HttpRequest | None
) -> None:
    _assert_can_manage_target(actor_access, membership)
    _assert_not_last_owner(membership)
    WorkspaceMembership.objects.filter(
        workspace__organization_id=membership.organization_id, user_id=membership.user_id
    ).delete()
    audit.record(
        AuditAction.ORG_MEMBER_REMOVED,
        actor=actor_access.membership.user,
        request=request,
        organization_id=membership.organization_id,
        target=membership,
        metadata={"user_id": str(membership.user_id)},
    )
    membership.delete()


# -----------------------------------------------------------------------------
# Invitations
# -----------------------------------------------------------------------------
@transaction.atomic
def create_invitation(
    *,
    actor_access: OrganizationAccess,
    email: str,
    role: str,
    workspace: Workspace | None = None,
    workspace_role: str = "",
    request: HttpRequest | None = None,
) -> tuple[Invitation, str]:
    org = actor_access.organization
    email = UserManager.normalize_email_address(email)
    _assert_can_assign(actor_access, role)
    if workspace is not None and workspace.organization_id != org.id:
        # Defensive: serializer already restricts choices to this org.
        raise ServiceError("Workspace not found.", code="invalid_workspace")
    if workspace is not None and not workspace_role:
        raise ServiceError("workspace_role is required when workspace is set.", code="workspace_role_required")
    if OrganizationMembership.objects.filter(organization=org, user__email=email, is_active=True).exists():
        raise ConflictError("This person is already a member of the organization.", code="already_member")
    if Invitation.objects.filter(organization=org, email=email, status=InvitationStatus.PENDING).exists():
        raise ConflictError("A pending invitation already exists for this email.", code="invitation_exists")
    from apps.billing.usage import check_seat_available

    check_seat_available(org)

    raw_token = secrets.token_urlsafe(32)
    invitation = Invitation.objects.create(
        organization=org,
        email=email,
        role=role,
        workspace=workspace,
        workspace_role=workspace_role if workspace else "",
        token_hash=hash_token(raw_token),
        expires_at=timezone.now() + settings.INVITATION_EXPIRY,
        invited_by=actor_access.membership.user,
    )
    inviter = actor_access.membership.user
    queue_email(
        to=email,
        subject=f"You've been invited to join {org.name} on ResolveAI",
        body=(
            f"{inviter.get_full_name()} invited you to join {org.name} on ResolveAI.\n\n"
            f"Accept the invitation: {settings.FRONTEND_URL}/invite?token={raw_token}\n\n"
            f"This link expires on {invitation.expires_at:%Y-%m-%d %H:%M} UTC."
        ),
    )
    audit.record(
        AuditAction.INVITATION_CREATED,
        actor=inviter,
        request=request,
        organization_id=org.id,
        target=invitation,
        metadata={"email": email, "role": role, "workspace_id": str(workspace.id) if workspace else None},
    )
    return invitation, raw_token


def revoke_invitation(
    *, invitation: Invitation, actor_access: OrganizationAccess, request: HttpRequest | None
) -> Invitation:
    if invitation.status != InvitationStatus.PENDING:
        raise ConflictError("Only pending invitations can be revoked.", code="invitation_not_pending")
    invitation.status = InvitationStatus.REVOKED
    invitation.save(update_fields=["status", "updated_at"])
    audit.record(
        AuditAction.INVITATION_REVOKED,
        actor=actor_access.membership.user,
        request=request,
        organization_id=invitation.organization_id,
        target=invitation,
    )
    return invitation


def get_usable_invitation(raw_token: str) -> Invitation | None:
    if not raw_token:
        return None
    invitation = (
        Invitation.objects.select_related("organization", "invited_by", "workspace")
        .filter(token_hash=hash_token(raw_token))
        .first()
    )
    if invitation is None or not invitation.is_usable:
        return None
    return invitation


@transaction.atomic
def accept_invitation(*, raw_token: str, user: User, request: HttpRequest | None = None) -> OrganizationMembership:
    invitation = Invitation.objects.select_for_update().filter(token_hash=hash_token(raw_token or "")).first()
    if invitation is None or not invitation.is_usable:
        raise ServiceError("This invitation is invalid or has expired.", code="invalid_invitation")
    if invitation.email != user.email:
        raise ServiceError(
            "This invitation was sent to a different email address.", code="invitation_email_mismatch", status_code=403
        )

    membership, created = OrganizationMembership.objects.get_or_create(
        organization_id=invitation.organization_id,
        user=user,
        defaults={"role": invitation.role, "invited_by": invitation.invited_by},
    )
    if not created and not membership.is_active:
        membership.is_active = True
        membership.role = invitation.role
        membership.save(update_fields=["is_active", "role", "updated_at"])

    if invitation.workspace_id:
        WorkspaceMembership.objects.update_or_create(
            workspace_id=invitation.workspace_id,
            user=user,
            defaults={"role": invitation.workspace_role, "is_active": True},
        )

    # Receiving the tokenized email proves ownership of the address.
    if user.email_verified_at is None:
        user.email_verified_at = timezone.now()
        user.save(update_fields=["email_verified_at", "updated_at"])

    invitation.status = InvitationStatus.ACCEPTED
    invitation.accepted_by = user
    invitation.accepted_at = timezone.now()
    invitation.save(update_fields=["status", "accepted_by", "accepted_at", "updated_at"])
    audit.record(
        AuditAction.INVITATION_ACCEPTED,
        actor=user,
        request=request,
        organization_id=invitation.organization_id,
        target=invitation,
    )
    return membership
