from __future__ import annotations

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone

from common.models import BaseModel
from common.rbac import OrganizationRole, WorkspaceRole

__all__ = ["Invitation", "InvitationStatus", "Organization", "OrganizationMembership", "OrganizationRole"]


class Organization(BaseModel):
    """Billing and ownership boundary. Owns one or more workspaces."""

    name = models.CharField(max_length=120)
    slug = models.SlugField(max_length=80, unique=True)
    # ISO 3166-1 alpha-2. Drives payment-provider selection (IN -> Razorpay).
    country = models.CharField(max_length=2, blank=True, default="")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class OrganizationMembership(BaseModel):
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="memberships")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="organization_memberships"
    )
    role = models.CharField(max_length=20, choices=OrganizationRole.choices, default=OrganizationRole.MEMBER)
    is_active = models.BooleanField(default=True)
    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        ordering = ["created_at"]
        constraints = [
            models.UniqueConstraint(fields=["organization", "user"], name="org_membership_unique_user"),
        ]
        indexes = [
            models.Index(fields=["user", "is_active"], name="org_membership_user_active"),
        ]

    def __str__(self) -> str:
        return f"{self.user_id} @ {self.organization_id} ({self.role})"


class InvitationStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    ACCEPTED = "accepted", "Accepted"
    REVOKED = "revoked", "Revoked"


class Invitation(BaseModel):
    """Invite an email address into an organization (and optionally a workspace).

    Only a SHA-256 hash of the token is stored; the raw token exists solely in
    the invitation email.
    """

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="invitations")
    email = models.EmailField(max_length=254)
    role = models.CharField(max_length=20, choices=OrganizationRole.choices, default=OrganizationRole.MEMBER)
    workspace = models.ForeignKey(
        "workspaces.Workspace", null=True, blank=True, on_delete=models.CASCADE, related_name="invitations"
    )
    workspace_role = models.CharField(max_length=20, choices=WorkspaceRole.choices, blank=True, default="")
    token_hash = models.CharField(max_length=64, unique=True)
    status = models.CharField(max_length=20, choices=InvitationStatus.choices, default=InvitationStatus.PENDING)
    expires_at = models.DateTimeField()
    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    accepted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    accepted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "email"],
                condition=Q(status="pending"),
                name="invitation_one_pending_per_email",
            ),
            models.CheckConstraint(
                condition=Q(workspace__isnull=True, workspace_role="")
                | Q(workspace__isnull=False) & ~Q(workspace_role=""),
                name="invitation_workspace_role_consistent",
            ),
        ]

    def __str__(self) -> str:
        return f"Invitation({self.email} -> {self.organization_id})"

    @property
    def is_expired(self) -> bool:
        return timezone.now() >= self.expires_at

    @property
    def is_usable(self) -> bool:
        return self.status == InvitationStatus.PENDING and not self.is_expired
