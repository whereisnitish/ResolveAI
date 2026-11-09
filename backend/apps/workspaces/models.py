from __future__ import annotations

import secrets

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.functions import Lower

from common.models import BaseModel
from common.rbac import WorkspaceRole

__all__ = ["Tag", "Team", "Workspace", "WorkspaceMembership", "WorkspaceOwnedModel", "WorkspaceRole"]


def generate_public_id() -> str:
    """Public, non-secret identifier embedded in the website widget snippet."""
    return f"ws_{secrets.token_urlsafe(16)}"


class Workspace(BaseModel):
    """Support environment and data-isolation boundary within an organization."""

    organization = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="workspaces")
    name = models.CharField(max_length=120)
    slug = models.SlugField(max_length=80)
    public_id = models.CharField(max_length=40, unique=True, default=generate_public_id, editable=False)
    timezone = models.CharField(max_length=64, default="UTC")
    is_default = models.BooleanField(default=False)
    # Monotonic counter for human-friendly conversation numbers (#1, #2, ...).
    # Incremented under a row lock in conversations.services.
    conversation_seq = models.PositiveIntegerField(default=0, editable=False)
    archived_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["organization", "slug"], name="workspace_unique_slug_per_org"),
            models.UniqueConstraint(
                fields=["organization"],
                condition=models.Q(is_default=True),
                name="workspace_one_default_per_org",
            ),
        ]

    def __str__(self) -> str:
        return self.name

    @property
    def is_archived(self) -> bool:
        return self.archived_at is not None


class WorkspaceMembership(BaseModel):
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="memberships")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="workspace_memberships")
    role = models.CharField(max_length=20, choices=WorkspaceRole.choices, default=WorkspaceRole.AGENT)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["created_at"]
        constraints = [
            models.UniqueConstraint(fields=["workspace", "user"], name="workspace_membership_unique_user"),
        ]
        indexes = [
            models.Index(fields=["user", "is_active"], name="ws_membership_user_active"),
        ]

    def __str__(self) -> str:
        return f"{self.user_id} @ {self.workspace_id} ({self.role})"


class WorkspaceOwnedModel(BaseModel):
    """Base for every tenant-owned record (customers, conversations, agents, ...).

    Carries both organization and workspace so that org-level queries
    (billing, analytics) and workspace-level isolation are cheap and explicit.
    The organization is always derived from the workspace — never taken from
    client input.
    """

    organization = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="+")
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="+")

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        if self.workspace_id and not self.organization_id:
            self.organization_id = self.workspace.organization_id
        elif self.workspace_id and self.workspace.organization_id != self.organization_id:
            raise ValidationError("Workspace does not belong to the record's organization.")
        super().save(*args, **kwargs)


class Team(WorkspaceOwnedModel):
    """A group of agents conversations can be routed to (e.g. "Billing", "Tier 2")."""

    name = models.CharField(max_length=80)
    members = models.ManyToManyField(settings.AUTH_USER_MODEL, related_name="support_teams", blank=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint("workspace", Lower("name"), name="team_unique_name_per_workspace"),
        ]

    def __str__(self) -> str:
        return self.name


class Tag(WorkspaceOwnedModel):
    """Workspace-level label applied to customers and conversations."""

    name = models.CharField(max_length=50)
    color = models.CharField(max_length=7, default="#6366f1")

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint("workspace", Lower("name"), name="tag_unique_name_per_workspace"),
        ]

    def __str__(self) -> str:
        return self.name
