"""Central role and permission definitions.

This module is the single source of truth for "who can do what". Views
declare the permission they need; they never compare role names directly.

Model
-----
* Organization roles govern the org itself (settings, members, billing).
* Workspace roles govern support data inside one workspace.
* Org Owners/Admins implicitly act as workspace Admin in every workspace of
  their organization. Org Members and Billing Admins only see workspaces
  where they hold an explicit, active WorkspaceMembership.
"""

from __future__ import annotations

from django.db import models


class OrganizationRole(models.TextChoices):
    OWNER = "owner", "Owner"
    ADMIN = "admin", "Admin"
    MEMBER = "member", "Member"
    BILLING_ADMIN = "billing_admin", "Billing Admin"


class WorkspaceRole(models.TextChoices):
    ADMIN = "admin", "Admin"
    SUPERVISOR = "supervisor", "Supervisor"
    AGENT = "agent", "Agent"
    VIEWER = "viewer", "Viewer"


class Perm:
    """Permission codes. Plain strings so they serialize cleanly to the frontend."""

    # Organization scope
    ORG_VIEW = "org.view"
    ORG_UPDATE = "org.update"
    ORG_DELETE = "org.delete"
    ORG_MEMBERS_VIEW = "org.members.view"
    ORG_MEMBERS_MANAGE = "org.members.manage"
    ORG_OWNERSHIP_MANAGE = "org.ownership.manage"
    ORG_WORKSPACES_CREATE = "org.workspaces.create"
    ORG_BILLING_VIEW = "org.billing.view"
    ORG_BILLING_MANAGE = "org.billing.manage"
    ORG_AUDIT_VIEW = "org.audit.view"
    ORG_ANALYTICS_VIEW = "org.analytics.view"

    # Workspace scope
    WORKSPACE_VIEW = "workspace.view"
    WORKSPACE_UPDATE = "workspace.update"
    WORKSPACE_MEMBERS_VIEW = "workspace.members.view"
    WORKSPACE_MEMBERS_MANAGE = "workspace.members.manage"
    CONVERSATIONS_VIEW = "conversations.view"
    CONVERSATIONS_REPLY = "conversations.reply"
    CONVERSATIONS_ASSIGN = "conversations.assign"
    CONVERSATIONS_MANAGE = "conversations.manage"
    CUSTOMERS_VIEW = "customers.view"
    CUSTOMERS_MANAGE = "customers.manage"
    AI_AGENTS_VIEW = "ai_agents.view"
    AI_AGENTS_MANAGE = "ai_agents.manage"
    KNOWLEDGE_VIEW = "knowledge.view"
    KNOWLEDGE_MANAGE = "knowledge.manage"
    WORKFLOWS_VIEW = "workflows.view"
    WORKFLOWS_MANAGE = "workflows.manage"
    ANALYTICS_VIEW = "analytics.view"
    INTEGRATIONS_MANAGE = "integrations.manage"


_ORG_ADMIN_PERMS = frozenset(
    {
        Perm.ORG_VIEW,
        Perm.ORG_UPDATE,
        Perm.ORG_MEMBERS_VIEW,
        Perm.ORG_MEMBERS_MANAGE,
        Perm.ORG_WORKSPACES_CREATE,
        Perm.ORG_BILLING_VIEW,
        Perm.ORG_AUDIT_VIEW,
        Perm.ORG_ANALYTICS_VIEW,
    }
)

ORG_ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    OrganizationRole.OWNER: _ORG_ADMIN_PERMS | {Perm.ORG_DELETE, Perm.ORG_OWNERSHIP_MANAGE, Perm.ORG_BILLING_MANAGE},
    OrganizationRole.ADMIN: _ORG_ADMIN_PERMS,
    OrganizationRole.BILLING_ADMIN: frozenset(
        {Perm.ORG_VIEW, Perm.ORG_MEMBERS_VIEW, Perm.ORG_BILLING_VIEW, Perm.ORG_BILLING_MANAGE}
    ),
    OrganizationRole.MEMBER: frozenset({Perm.ORG_VIEW}),
}

_VIEWER_PERMS = frozenset(
    {
        Perm.WORKSPACE_VIEW,
        Perm.WORKSPACE_MEMBERS_VIEW,
        Perm.CONVERSATIONS_VIEW,
        Perm.CUSTOMERS_VIEW,
        Perm.AI_AGENTS_VIEW,
        Perm.KNOWLEDGE_VIEW,
        Perm.WORKFLOWS_VIEW,
        Perm.ANALYTICS_VIEW,
    }
)
_AGENT_PERMS = _VIEWER_PERMS | {
    Perm.CONVERSATIONS_REPLY,
    Perm.CONVERSATIONS_ASSIGN,
    Perm.CUSTOMERS_MANAGE,
}
_SUPERVISOR_PERMS = _AGENT_PERMS | {
    Perm.CONVERSATIONS_MANAGE,
    Perm.KNOWLEDGE_MANAGE,
    Perm.WORKFLOWS_MANAGE,
}
_WS_ADMIN_PERMS = _SUPERVISOR_PERMS | {
    Perm.WORKSPACE_UPDATE,
    Perm.WORKSPACE_MEMBERS_MANAGE,
    Perm.AI_AGENTS_MANAGE,
    Perm.INTEGRATIONS_MANAGE,
}

WORKSPACE_ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    WorkspaceRole.ADMIN: _WS_ADMIN_PERMS,
    WorkspaceRole.SUPERVISOR: _SUPERVISOR_PERMS,
    WorkspaceRole.AGENT: _AGENT_PERMS,
    WorkspaceRole.VIEWER: _VIEWER_PERMS,
}

# Org roles that implicitly grant workspace Admin across the organization.
ORG_ROLES_WITH_IMPLICIT_WORKSPACE_ADMIN = frozenset({OrganizationRole.OWNER, OrganizationRole.ADMIN})

# Roles an actor may assign to others. Only owners can mint owners.
ASSIGNABLE_ORG_ROLES: dict[str, frozenset[str]] = {
    OrganizationRole.OWNER: frozenset(OrganizationRole.values),
    OrganizationRole.ADMIN: frozenset(
        {OrganizationRole.ADMIN, OrganizationRole.MEMBER, OrganizationRole.BILLING_ADMIN}
    ),
}


def org_permissions(role: str) -> frozenset[str]:
    return ORG_ROLE_PERMISSIONS.get(role, frozenset())


def workspace_permissions(role: str | None) -> frozenset[str]:
    if role is None:
        return frozenset()
    return WORKSPACE_ROLE_PERMISSIONS.get(role, frozenset())


def effective_workspace_role(org_role: str, workspace_role: str | None) -> str | None:
    """Combine org and explicit workspace roles into the effective workspace role."""
    if org_role in ORG_ROLES_WITH_IMPLICIT_WORKSPACE_ADMIN:
        return WorkspaceRole.ADMIN
    return workspace_role


def workspace_roles_with(perm: str) -> list[str]:
    """Workspace roles whose permission set includes ``perm``."""
    return [role for role, perms in WORKSPACE_ROLE_PERMISSIONS.items() if perm in perms]
