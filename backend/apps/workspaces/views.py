from __future__ import annotations

import uuid
from typing import Any

from django.db.models import QuerySet
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework import generics, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.organizations.models import OrganizationMembership
from apps.tenancy.access import accessible_workspaces
from apps.tenancy.views import OrganizationScopedViewMixin, WorkspaceScopedViewMixin
from apps.workspaces import services
from apps.workspaces.models import Workspace, WorkspaceMembership
from apps.workspaces.serializers import (
    WorkspaceCreateSerializer,
    WorkspaceMemberCreateSerializer,
    WorkspaceMembershipSerializer,
    WorkspaceMemberUpdateSerializer,
    WorkspaceSerializer,
    WorkspaceUpdateSerializer,
)
from common.rbac import Perm, effective_workspace_role


def _workspace_roles(user: Any, workspaces: list[Workspace]) -> dict:
    org_roles = dict(
        OrganizationMembership.objects.filter(user=user, is_active=True).values_list("organization_id", "role")
    )
    ws_roles = dict(
        WorkspaceMembership.objects.filter(user=user, is_active=True, workspace__in=workspaces).values_list(
            "workspace_id", "role"
        )
    )
    return {
        ws.id: effective_workspace_role(org_roles.get(ws.organization_id, ""), ws_roles.get(ws.id)) for ws in workspaces
    }


class WorkspaceListView(generics.ListAPIView):
    """All workspaces the caller can access across their organizations."""

    permission_classes = [IsAuthenticated]
    serializer_class = WorkspaceSerializer
    search_fields = ["name"]

    def get_queryset(self) -> QuerySet[Workspace]:
        qs = accessible_workspaces(self.request.user).order_by("organization__name", "-is_default", "name")
        org = self.request.query_params.get("organization")
        if not org:
            return qs
        try:
            return qs.filter(organization_id=uuid.UUID(org))
        except ValueError:
            return qs.none()

    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        page = self.paginate_queryset(self.filter_queryset(self.get_queryset()))
        roles = _workspace_roles(request.user, page)
        return self.get_paginated_response(WorkspaceSerializer(page, many=True, context={"roles": roles}).data)


class OrganizationWorkspaceCreateView(OrganizationScopedViewMixin, APIView):
    permission_by_action = {"post": Perm.ORG_WORKSPACES_CREATE}

    @extend_schema(request=WorkspaceCreateSerializer, responses={201: WorkspaceSerializer})
    def post(self, request: Request, organization_id: str) -> Response:
        serializer = WorkspaceCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        from apps.billing.usage import check_workspace_available

        check_workspace_available(self.organization)
        workspace = services.create_workspace(
            organization=self.organization,
            name=serializer.validated_data["name"],
            timezone=serializer.validated_data["timezone"],
            created_by=request.user,
            request=request,
        )
        roles = _workspace_roles(request.user, [workspace])
        return Response(WorkspaceSerializer(workspace, context={"roles": roles}).data, status=status.HTTP_201_CREATED)


class WorkspaceDetailView(WorkspaceScopedViewMixin, APIView):
    permission_by_action = {"get": Perm.WORKSPACE_VIEW, "patch": Perm.WORKSPACE_UPDATE}

    def _respond(self, workspace: Workspace) -> Response:
        access = self.get_workspace_access()
        return Response(WorkspaceSerializer(workspace, context={"roles": {workspace.id: access.role}}).data)

    @extend_schema(responses={200: WorkspaceSerializer})
    def get(self, request: Request, workspace_id: str) -> Response:
        return self._respond(self.workspace)

    @extend_schema(request=WorkspaceUpdateSerializer, responses={200: WorkspaceSerializer})
    def patch(self, request: Request, workspace_id: str) -> Response:
        serializer = WorkspaceUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        workspace = services.update_workspace(
            workspace=self.workspace, data=serializer.validated_data, actor=request.user, request=request
        )
        return self._respond(workspace)


class WorkspaceMemberListCreateView(WorkspaceScopedViewMixin, generics.GenericAPIView):
    permission_by_action = {"get": Perm.WORKSPACE_MEMBERS_VIEW, "post": Perm.WORKSPACE_MEMBERS_MANAGE}
    serializer_class = WorkspaceMembershipSerializer
    search_fields = ["user__email", "user__full_name"]

    def get_queryset(self) -> QuerySet[WorkspaceMembership]:
        return WorkspaceMembership.objects.filter(workspace=self.workspace).select_related("user")

    @extend_schema(responses={200: WorkspaceMembershipSerializer(many=True)})
    def get(self, request: Request, workspace_id: str) -> Response:
        page = self.paginate_queryset(self.filter_queryset(self.get_queryset()))
        return self.get_paginated_response(WorkspaceMembershipSerializer(page, many=True).data)

    @extend_schema(request=WorkspaceMemberCreateSerializer, responses={201: WorkspaceMembershipSerializer})
    def post(self, request: Request, workspace_id: str) -> Response:
        serializer = WorkspaceMemberCreateSerializer(data=request.data, context={"workspace": self.workspace})
        serializer.is_valid(raise_exception=True)
        membership = services.add_workspace_member(
            workspace=self.workspace,
            user=serializer.validated_data["user_id"],
            role=serializer.validated_data["role"],
            actor=request.user,
            request=request,
        )
        return Response(WorkspaceMembershipSerializer(membership).data, status=status.HTTP_201_CREATED)


class WorkspaceMemberDetailView(WorkspaceScopedViewMixin, APIView):
    permission_by_action = {"patch": Perm.WORKSPACE_MEMBERS_MANAGE, "delete": Perm.WORKSPACE_MEMBERS_MANAGE}

    def _get_membership(self, membership_id: str) -> WorkspaceMembership:
        return get_object_or_404(
            WorkspaceMembership.objects.select_related("user", "workspace"), id=membership_id, workspace=self.workspace
        )

    @extend_schema(request=WorkspaceMemberUpdateSerializer, responses={200: WorkspaceMembershipSerializer})
    def patch(self, request: Request, workspace_id: str, membership_id: str) -> Response:
        serializer = WorkspaceMemberUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        membership = services.update_workspace_member(
            membership=self._get_membership(membership_id),
            data=serializer.validated_data,
            actor=request.user,
            request=request,
        )
        return Response(WorkspaceMembershipSerializer(membership).data)

    @extend_schema(responses={204: None})
    def delete(self, request: Request, workspace_id: str, membership_id: str) -> Response:
        services.remove_workspace_member(
            membership=self._get_membership(membership_id), actor=request.user, request=request
        )
        return Response(status=status.HTTP_204_NO_CONTENT)
