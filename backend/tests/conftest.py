from __future__ import annotations

from dataclasses import dataclass

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.organizations.models import Organization, OrganizationMembership
from apps.workspaces.models import Workspace, WorkspaceMembership
from common.rbac import OrganizationRole, WorkspaceRole
from tests.factories import (
    OrganizationFactory,
    OrganizationMembershipFactory,
    UserFactory,
    WorkspaceFactory,
    WorkspaceMembershipFactory,
)


@pytest.fixture(autouse=True)
def _db(db):  # type: ignore[no-untyped-def]
    """All tests in this project touch the database."""


@pytest.fixture(autouse=True)
def _clear_cache():  # type: ignore[no-untyped-def]
    from django.core.cache import cache

    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def api_client() -> APIClient:
    return APIClient()


@pytest.fixture
def client_for():  # type: ignore[no-untyped-def]
    def _make(user: User) -> APIClient:
        c = APIClient()
        c.force_login(user)
        return c

    return _make


@dataclass
class Tenant:
    """An organization with one workspace and a user per role."""

    org: Organization
    workspace: Workspace
    owner: User
    admin: User
    member: User
    billing_admin: User
    ws_agent: User  # org member with explicit workspace Agent role
    ws_viewer: User  # org member with explicit workspace Viewer role

    def membership(self, user: User) -> OrganizationMembership:
        return OrganizationMembership.objects.get(organization=self.org, user=user)

    def ws_membership(self, user: User) -> WorkspaceMembership:
        return WorkspaceMembership.objects.get(workspace=self.workspace, user=user)


def make_tenant(name: str) -> Tenant:
    org = OrganizationFactory(name=name)
    workspace = WorkspaceFactory(organization=org, is_default=True)
    users = {}
    for role in (
        OrganizationRole.OWNER,
        OrganizationRole.ADMIN,
        OrganizationRole.MEMBER,
        OrganizationRole.BILLING_ADMIN,
    ):
        user = UserFactory()
        OrganizationMembershipFactory(organization=org, user=user, role=role)
        users[role] = user
    ws_users = {}
    for ws_role in (WorkspaceRole.AGENT, WorkspaceRole.VIEWER):
        user = UserFactory()
        OrganizationMembershipFactory(organization=org, user=user, role=OrganizationRole.MEMBER)
        WorkspaceMembershipFactory(workspace=workspace, user=user, role=ws_role)
        ws_users[ws_role] = user
    # Fixture tenants are paying customers on a roomy plan; limit behaviour has its own tests.
    from apps.billing.models import Subscription
    from apps.billing.usage import get_plan

    Subscription.objects.create(organization=org, plan=get_plan("scale"), status="active")
    return Tenant(
        org=org,
        workspace=workspace,
        owner=users[OrganizationRole.OWNER],
        admin=users[OrganizationRole.ADMIN],
        member=users[OrganizationRole.MEMBER],
        billing_admin=users[OrganizationRole.BILLING_ADMIN],
        ws_agent=ws_users[WorkspaceRole.AGENT],
        ws_viewer=ws_users[WorkspaceRole.VIEWER],
    )


@pytest.fixture
def tenant_a() -> Tenant:
    return make_tenant("Acme")


@pytest.fixture
def tenant_b() -> Tenant:
    return make_tenant("Globex")


@pytest.fixture
def csrf_client() -> APIClient:
    """Client that enforces CSRF like a real browser would."""
    return APIClient(enforce_csrf_checks=True)
