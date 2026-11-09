"""DRF building blocks for tenant-scoped endpoints.

Usage::

    class CustomerViewSet(WorkspaceScopedViewMixin, viewsets.ModelViewSet):
        permission_by_action = {"list": Perm.CUSTOMERS_VIEW, "create": Perm.CUSTOMERS_MANAGE, ...}

        def get_queryset(self):
            return Customer.objects.filter(workspace=self.workspace)

Behaviour:
  * The tenant ID comes from the URL (``organization_id`` / ``workspace_id``)
    and is resolved against the caller's memberships on every request.
  * No membership (or inactive/archived) -> 404, so tenant IDs cannot be probed.
  * Membership without the action's permission -> 403.
  * Actions missing from ``permission_by_action`` are denied by default.
"""

from __future__ import annotations

from typing import Any

from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.request import Request

from apps.organizations.models import Organization
from apps.tenancy.access import (
    OrganizationAccess,
    WorkspaceAccess,
    get_organization_access,
    get_workspace_access,
)
from apps.workspaces.models import Workspace


def _required_permission(view: Any, request: Request) -> str | None:
    mapping: dict[str, str] = getattr(view, "permission_by_action", {}) or {}
    action = getattr(view, "action", None) or request.method.lower()
    if action == "metadata":  # OPTIONS
        return None
    if action not in mapping:
        raise PermissionDenied("This action is not permitted.")
    return mapping[action]


class _TenantPermission(BasePermission):
    access_attr: str

    def has_permission(self, request: Request, view: Any) -> bool:
        access = getattr(view, self.access_attr)()
        perm = _required_permission(view, request)
        if perm is not None and not access.has(perm):
            raise PermissionDenied("You do not have permission to perform this action.")
        return True


class HasOrganizationPermission(_TenantPermission):
    access_attr = "get_organization_access"


class HasWorkspacePermission(_TenantPermission):
    access_attr = "get_workspace_access"


class OrganizationScopedViewMixin:
    organization_url_kwarg = "organization_id"
    permission_classes = [IsAuthenticated, HasOrganizationPermission]
    permission_by_action: dict[str, str] = {}

    _org_access: OrganizationAccess | None = None

    def get_organization_access(self) -> OrganizationAccess:
        if self._org_access is None:
            org_id = self.kwargs.get(self.organization_url_kwarg)  # type: ignore[attr-defined]
            access = get_organization_access(self.request.user, org_id)  # type: ignore[attr-defined]
            if access is None:
                raise NotFound()
            self._org_access = access
        return self._org_access

    @property
    def organization(self) -> Organization:
        return self.get_organization_access().organization


class WorkspaceScopedViewMixin:
    workspace_url_kwarg = "workspace_id"
    permission_classes = [IsAuthenticated, HasWorkspacePermission]
    permission_by_action: dict[str, str] = {}

    _ws_access: WorkspaceAccess | None = None

    def get_workspace_access(self) -> WorkspaceAccess:
        if self._ws_access is None:
            ws_id = self.kwargs.get(self.workspace_url_kwarg)  # type: ignore[attr-defined]
            access = get_workspace_access(self.request.user, ws_id)  # type: ignore[attr-defined]
            if access is None:
                raise NotFound()
            self._ws_access = access
        return self._ws_access

    @property
    def workspace(self) -> Workspace:
        return self.get_workspace_access().workspace
