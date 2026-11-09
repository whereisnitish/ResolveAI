from __future__ import annotations

from typing import Any

from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.analytics import services
from apps.tenancy.views import OrganizationScopedViewMixin, WorkspaceScopedViewMixin
from apps.workspaces.models import Workspace
from common.exceptions import ServiceError
from common.rbac import Perm

RANGE_PARAMS = [
    OpenApiParameter("start", str, description="YYYY-MM-DD"),
    OpenApiParameter("end", str, description="YYYY-MM-DD"),
]


def _range(request: Request) -> tuple[Any, Any]:
    try:
        return services.parse_range(request.query_params.get("start"), request.query_params.get("end"))
    except ValueError as exc:
        raise ServiceError(str(exc), code="invalid_range") from exc


class WorkspaceAnalyticsView(WorkspaceScopedViewMixin, APIView):
    permission_by_action = {"get": Perm.ANALYTICS_VIEW}

    @extend_schema(parameters=RANGE_PARAMS, responses={200: dict})
    def get(self, request: Request, workspace_id: Any) -> Response:
        start, end = _range(request)
        return Response(services.compute([self.workspace.id], start, end))


class OrganizationAnalyticsView(OrganizationScopedViewMixin, APIView):
    """Roll-up across all workspaces of the organization (owners/admins)."""

    permission_by_action = {"get": Perm.ORG_ANALYTICS_VIEW}

    @extend_schema(parameters=RANGE_PARAMS, responses={200: dict})
    def get(self, request: Request, organization_id: Any) -> Response:
        start, end = _range(request)
        ids = list(
            Workspace.objects.filter(organization=self.organization, archived_at__isnull=True).values_list(
                "id", flat=True
            )
        )
        return Response(services.compute(ids, start, end))
