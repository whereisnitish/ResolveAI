from __future__ import annotations

from django.db.models import QuerySet
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework import generics, status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from apps.accounts.models import User
from apps.accounts.serializers import MeSerializer, TokenSerializer, build_me_payload
from apps.audit.models import AuditLog
from apps.organizations import services
from apps.organizations.models import Invitation, Organization, OrganizationMembership
from apps.organizations.serializers import (
    AuditLogSerializer,
    InvitationCreateSerializer,
    InvitationPreviewSerializer,
    InvitationSerializer,
    OrganizationCreateSerializer,
    OrganizationMembershipSerializer,
    OrganizationMembershipUpdateSerializer,
    OrganizationSerializer,
    OrganizationUpdateSerializer,
)
from apps.tenancy.access import accessible_organizations
from apps.tenancy.views import OrganizationScopedViewMixin
from common.authentication import CsrfProtectedAPIViewMixin
from common.exceptions import ServiceError
from common.rbac import Perm


def _roles_for(user: User) -> dict:
    return dict(OrganizationMembership.objects.filter(user=user, is_active=True).values_list("organization_id", "role"))


class OrganizationListCreateView(generics.GenericAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = OrganizationSerializer

    def get_queryset(self) -> QuerySet[Organization]:
        return accessible_organizations(self.request.user).order_by("name")

    @extend_schema(responses={200: OrganizationSerializer(many=True)})
    def get(self, request: Request) -> Response:
        page = self.paginate_queryset(self.get_queryset())
        data = OrganizationSerializer(page, many=True, context={"roles": _roles_for(request.user)}).data
        return self.get_paginated_response(data)

    @extend_schema(request=OrganizationCreateSerializer, responses={201: OrganizationSerializer})
    def post(self, request: Request) -> Response:
        serializer = OrganizationCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        org, _ = services.create_organization(
            name=serializer.validated_data["name"],
            country=serializer.validated_data.get("country", ""),
            owner=request.user,
            request=request,
        )
        data = OrganizationSerializer(org, context={"roles": _roles_for(request.user)}).data
        return Response(data, status=status.HTTP_201_CREATED)


class OrganizationDetailView(OrganizationScopedViewMixin, APIView):
    permission_by_action = {"get": Perm.ORG_VIEW, "patch": Perm.ORG_UPDATE}

    @extend_schema(responses={200: OrganizationSerializer})
    def get(self, request: Request, organization_id: str) -> Response:
        access = self.get_organization_access()
        return Response(
            OrganizationSerializer(access.organization, context={"roles": {access.organization.id: access.role}}).data
        )

    @extend_schema(request=OrganizationUpdateSerializer, responses={200: OrganizationSerializer})
    def patch(self, request: Request, organization_id: str) -> Response:
        access = self.get_organization_access()
        serializer = OrganizationUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        org = services.update_organization(
            organization=access.organization, data=serializer.validated_data, actor=request.user, request=request
        )
        return Response(OrganizationSerializer(org, context={"roles": {org.id: access.role}}).data)


class OrganizationMemberListView(OrganizationScopedViewMixin, generics.ListAPIView):
    permission_by_action = {"get": Perm.ORG_MEMBERS_VIEW}
    serializer_class = OrganizationMembershipSerializer
    search_fields = ["user__email", "user__full_name"]
    ordering_fields = ["created_at", "role"]

    def get_queryset(self) -> QuerySet[OrganizationMembership]:
        return OrganizationMembership.objects.filter(organization=self.organization).select_related("user")


class OrganizationMemberDetailView(OrganizationScopedViewMixin, APIView):
    permission_by_action = {"patch": Perm.ORG_MEMBERS_MANAGE, "delete": Perm.ORG_MEMBERS_MANAGE}

    def _get_membership(self, membership_id: str) -> OrganizationMembership:
        return get_object_or_404(
            OrganizationMembership.objects.select_related("user"), id=membership_id, organization=self.organization
        )

    @extend_schema(request=OrganizationMembershipUpdateSerializer, responses={200: OrganizationMembershipSerializer})
    def patch(self, request: Request, organization_id: str, membership_id: str) -> Response:
        membership = self._get_membership(membership_id)
        serializer = OrganizationMembershipUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        membership = services.update_member(
            membership=membership,
            data=serializer.validated_data,
            actor_access=self.get_organization_access(),
            request=request,
        )
        return Response(OrganizationMembershipSerializer(membership).data)

    @extend_schema(responses={204: None})
    def delete(self, request: Request, organization_id: str, membership_id: str) -> Response:
        membership = self._get_membership(membership_id)
        services.remove_member(membership=membership, actor_access=self.get_organization_access(), request=request)
        return Response(status=status.HTTP_204_NO_CONTENT)


class InvitationListCreateView(OrganizationScopedViewMixin, generics.GenericAPIView):
    permission_by_action = {"get": Perm.ORG_MEMBERS_VIEW, "post": Perm.ORG_MEMBERS_MANAGE}
    serializer_class = InvitationSerializer

    def get_queryset(self) -> QuerySet[Invitation]:
        qs = Invitation.objects.filter(organization=self.organization).select_related("invited_by")
        status_filter = self.request.query_params.get("status")
        return qs.filter(status=status_filter) if status_filter else qs

    @extend_schema(responses={200: InvitationSerializer(many=True)})
    def get(self, request: Request, organization_id: str) -> Response:
        page = self.paginate_queryset(self.get_queryset())
        return self.get_paginated_response(InvitationSerializer(page, many=True).data)

    @extend_schema(request=InvitationCreateSerializer, responses={201: InvitationSerializer})
    def post(self, request: Request, organization_id: str) -> Response:
        serializer = InvitationCreateSerializer(data=request.data, context={"organization": self.organization})
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        invitation, _raw = services.create_invitation(
            actor_access=self.get_organization_access(),
            email=data["email"],
            role=data["role"],
            workspace=data.get("workspace"),
            workspace_role=data.get("workspace_role", ""),
            request=request,
        )
        return Response(InvitationSerializer(invitation).data, status=status.HTTP_201_CREATED)


class InvitationRevokeView(OrganizationScopedViewMixin, APIView):
    permission_by_action = {"post": Perm.ORG_MEMBERS_MANAGE}

    @extend_schema(request=None, responses={200: InvitationSerializer})
    def post(self, request: Request, organization_id: str, invitation_id: str) -> Response:
        invitation = get_object_or_404(Invitation, id=invitation_id, organization=self.organization)
        invitation = services.revoke_invitation(
            invitation=invitation, actor_access=self.get_organization_access(), request=request
        )
        return Response(InvitationSerializer(invitation).data)


class AuditLogListView(OrganizationScopedViewMixin, generics.ListAPIView):
    permission_by_action = {"get": Perm.ORG_AUDIT_VIEW}
    serializer_class = AuditLogSerializer
    search_fields = ["action", "actor_email"]

    def get_queryset(self) -> QuerySet[AuditLog]:
        qs = AuditLog.objects.filter(organization_id=self.organization.id)
        action = self.request.query_params.get("action")
        return qs.filter(action=action) if action else qs


class InvitationPreviewView(CsrfProtectedAPIViewMixin, APIView):
    """Public: lets the invite landing page show who invited whom."""

    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "auth"

    @extend_schema(request=TokenSerializer, responses={200: InvitationPreviewSerializer})
    def post(self, request: Request) -> Response:
        serializer = TokenSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        invitation = services.get_usable_invitation(serializer.validated_data["token"])
        if invitation is None:
            raise ServiceError("This invitation is invalid or has expired.", code="invalid_invitation", status_code=404)
        return Response(
            InvitationPreviewSerializer(
                {
                    "organization_name": invitation.organization.name,
                    "email": invitation.email,
                    "role": invitation.role,
                    "invited_by_name": invitation.invited_by.get_full_name() if invitation.invited_by else "",
                    "expires_at": invitation.expires_at,
                    "account_exists": User.objects.filter(email=invitation.email).exists(),
                }
            ).data
        )


class InvitationAcceptView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "auth"

    @extend_schema(request=TokenSerializer, responses={200: MeSerializer})
    def post(self, request: Request) -> Response:
        serializer = TokenSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.accept_invitation(raw_token=serializer.validated_data["token"], user=request.user, request=request)
        return Response(MeSerializer(build_me_payload(request.user)).data)
