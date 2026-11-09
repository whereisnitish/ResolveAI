"""Critical security tests: tenant isolation, IDOR, inactive members, anonymous access."""

from __future__ import annotations

import uuid

import pytest

from apps.workspaces.models import WorkspaceMembership
from common.rbac import WorkspaceRole
from tests.conftest import Tenant
from tests.factories import UserFactory, WorkspaceFactory, WorkspaceMembershipFactory

API = "/api/v1"


def org_urls(org_id: object, membership_id: object = None, invitation_id: object = None) -> list[tuple[str, str]]:
    m = membership_id or uuid.uuid4()
    i = invitation_id or uuid.uuid4()
    return [
        ("get", f"{API}/organizations/{org_id}/"),
        ("patch", f"{API}/organizations/{org_id}/"),
        ("get", f"{API}/organizations/{org_id}/members/"),
        ("patch", f"{API}/organizations/{org_id}/members/{m}/"),
        ("delete", f"{API}/organizations/{org_id}/members/{m}/"),
        ("get", f"{API}/organizations/{org_id}/invitations/"),
        ("post", f"{API}/organizations/{org_id}/invitations/"),
        ("post", f"{API}/organizations/{org_id}/invitations/{i}/revoke/"),
        ("post", f"{API}/organizations/{org_id}/workspaces/"),
        ("get", f"{API}/organizations/{org_id}/audit-logs/"),
    ]


def workspace_urls(ws_id: object, membership_id: object = None) -> list[tuple[str, str]]:
    m = membership_id or uuid.uuid4()
    return [
        ("get", f"{API}/workspaces/{ws_id}/"),
        ("patch", f"{API}/workspaces/{ws_id}/"),
        ("get", f"{API}/workspaces/{ws_id}/members/"),
        ("post", f"{API}/workspaces/{ws_id}/members/"),
        ("patch", f"{API}/workspaces/{ws_id}/members/{m}/"),
        ("delete", f"{API}/workspaces/{ws_id}/members/{m}/"),
    ]


class TestCrossOrganizationAccess:
    """(1) A user from Organization A cannot access Organization B data."""

    def test_owner_of_a_gets_404_on_every_org_b_endpoint(self, client_for, tenant_a: Tenant, tenant_b: Tenant):
        client = client_for(tenant_a.owner)
        b_membership = tenant_b.membership(tenant_b.member)
        for method, url in org_urls(tenant_b.org.id, membership_id=b_membership.id):
            response = getattr(client, method)(url, {}, format="json")
            assert response.status_code == 404, (method, url, response.status_code)

    def test_owner_of_a_cannot_modify_b_membership_via_own_org_url(self, client_for, tenant_a, tenant_b):
        """IDOR: a valid membership ID from org B under org A's URL must not resolve."""
        client = client_for(tenant_a.owner)
        b_membership = tenant_b.membership(tenant_b.member)
        url = f"{API}/organizations/{tenant_a.org.id}/members/{b_membership.id}/"
        assert client.patch(url, {"role": "admin"}, format="json").status_code == 404
        assert client.delete(url).status_code == 404
        b_membership.refresh_from_db()
        assert b_membership.role == "member"

    def test_org_list_only_contains_own_orgs(self, client_for, tenant_a, tenant_b):
        response = client_for(tenant_a.owner).get(f"{API}/organizations/")
        ids = {o["id"] for o in response.json()["results"]}
        assert ids == {str(tenant_a.org.id)}

    def test_audit_logs_do_not_leak_across_orgs(self, client_for, tenant_a, tenant_b):
        client_for(tenant_b.owner).patch(f"{API}/organizations/{tenant_b.org.id}/", {"name": "Secret"}, format="json")
        response = client_for(tenant_a.owner).get(f"{API}/organizations/{tenant_a.org.id}/audit-logs/")
        assert response.status_code == 200
        assert all(entry["actor_email"] != tenant_b.owner.email for entry in response.json()["results"])

    def test_invitation_cannot_target_workspace_of_other_org(self, client_for, tenant_a, tenant_b):
        response = client_for(tenant_a.owner).post(
            f"{API}/organizations/{tenant_a.org.id}/invitations/",
            {
                "email": "x@example.com",
                "role": "member",
                "workspace": str(tenant_b.workspace.id),
                "workspace_role": "agent",
            },
            format="json",
        )
        assert response.status_code == 400
        assert "workspace" in response.json()["error"]["details"]

    def test_cannot_add_user_from_other_org_to_workspace(self, client_for, tenant_a, tenant_b):
        response = client_for(tenant_a.owner).post(
            f"{API}/workspaces/{tenant_a.workspace.id}/members/",
            {"user_id": str(tenant_b.member.id), "role": "agent"},
            format="json",
        )
        assert response.status_code == 400
        assert not WorkspaceMembership.objects.filter(workspace=tenant_a.workspace, user=tenant_b.member).exists()


class TestWorkspaceUUIDGuessing:
    """(2) A user cannot access an unauthorized workspace by guessing its UUID."""

    def test_other_org_workspace_returns_404(self, client_for, tenant_a, tenant_b):
        client = client_for(tenant_a.owner)
        b_ws_member = tenant_b.ws_membership(tenant_b.ws_agent)
        for method, url in workspace_urls(tenant_b.workspace.id, membership_id=b_ws_member.id):
            response = getattr(client, method)(url, {}, format="json")
            assert response.status_code == 404, (method, url, response.status_code)

    def test_random_uuid_returns_404(self, client_for, tenant_a):
        assert client_for(tenant_a.owner).get(f"{API}/workspaces/{uuid.uuid4()}/").status_code == 404

    def test_malformed_ids_return_404_not_500(self, client_for, tenant_a):
        client = client_for(tenant_a.owner)
        assert client.get(f"{API}/workspaces/not-a-uuid/").status_code == 404
        assert client.get(f"{API}/organizations/1/").status_code == 404
        assert client.get(f"{API}/workspaces/?organization=not-a-uuid").json()["count"] == 0

    def test_same_org_member_without_workspace_membership_gets_404(self, client_for, tenant_a):
        other_ws = WorkspaceFactory(organization=tenant_a.org)
        client = client_for(tenant_a.ws_agent)
        assert client.get(f"{API}/workspaces/{other_ws.id}/").status_code == 404
        listed = {w["id"] for w in client.get(f"{API}/workspaces/").json()["results"]}
        assert str(other_ws.id) not in listed
        assert str(tenant_a.workspace.id) in listed

    def test_billing_admin_has_no_implicit_workspace_access(self, client_for, tenant_a):
        client = client_for(tenant_a.billing_admin)
        assert client.get(f"{API}/workspaces/{tenant_a.workspace.id}/").status_code == 404

    def test_org_admin_has_implicit_access_to_all_org_workspaces(self, client_for, tenant_a, tenant_b):
        other_ws = WorkspaceFactory(organization=tenant_a.org)
        client = client_for(tenant_a.admin)
        response = client.get(f"{API}/workspaces/{other_ws.id}/")
        assert response.status_code == 200
        assert response.json()["role"] == WorkspaceRole.ADMIN
        listed = {w["id"] for w in client.get(f"{API}/workspaces/").json()["results"]}
        assert listed == {str(tenant_a.workspace.id), str(other_ws.id)}

    def test_archived_workspace_is_inaccessible(self, client_for, tenant_a):
        from django.utils import timezone

        tenant_a.workspace.archived_at = timezone.now()
        tenant_a.workspace.save()
        assert client_for(tenant_a.owner).get(f"{API}/workspaces/{tenant_a.workspace.id}/").status_code == 404


class TestInactiveMembers:
    """(3) Inactive members cannot access workspace data."""

    def test_inactive_workspace_membership_denied(self, client_for, tenant_a):
        m = tenant_a.ws_membership(tenant_a.ws_agent)
        m.is_active = False
        m.save()
        client = client_for(tenant_a.ws_agent)
        assert client.get(f"{API}/workspaces/{tenant_a.workspace.id}/").status_code == 404
        assert client.get(f"{API}/workspaces/").json()["count"] == 0

    def test_inactive_org_membership_denies_org_and_all_workspaces(self, client_for, tenant_a):
        # ws_agent still has an *active* workspace membership; the org-level
        # deactivation must override it.
        m = tenant_a.membership(tenant_a.ws_agent)
        m.is_active = False
        m.save()
        client = client_for(tenant_a.ws_agent)
        assert client.get(f"{API}/organizations/{tenant_a.org.id}/").status_code == 404
        assert client.get(f"{API}/workspaces/{tenant_a.workspace.id}/").status_code == 404
        me = client.get(f"{API}/auth/me/").json()
        assert me["organizations"] == [] and me["workspaces"] == []

    def test_inactive_org_admin_loses_implicit_workspace_access(self, client_for, tenant_a):
        m = tenant_a.membership(tenant_a.admin)
        m.is_active = False
        m.save()
        assert client_for(tenant_a.admin).get(f"{API}/workspaces/{tenant_a.workspace.id}/").status_code == 404

    def test_deactivated_user_session_is_rejected(self, client_for, tenant_a):
        client = client_for(tenant_a.owner)
        tenant_a.owner.is_active = False
        tenant_a.owner.save()
        assert client.get(f"{API}/auth/me/").status_code == 403
        assert client.get(f"{API}/workspaces/{tenant_a.workspace.id}/").status_code == 403


class TestAnonymousAccess:
    """(5) Anonymous visitors cannot call privileged dashboard APIs."""

    def test_anonymous_denied_everywhere(self, api_client, tenant_a):
        urls = [
            ("get", f"{API}/auth/me/"),
            ("get", f"{API}/organizations/"),
            ("post", f"{API}/organizations/"),
            ("get", f"{API}/workspaces/"),
            *org_urls(tenant_a.org.id),
            *workspace_urls(tenant_a.workspace.id),
        ]
        for method, url in urls:
            response = getattr(api_client, method)(url, {}, format="json")
            assert response.status_code in (401, 403), (method, url, response.status_code)


class TestRolePermissions:
    @pytest.mark.parametrize(
        ("role_attr", "expected"),
        [("owner", 200), ("admin", 200), ("member", 403), ("billing_admin", 403)],
    )
    def test_org_update_permission(self, client_for, tenant_a, role_attr, expected):
        client = client_for(getattr(tenant_a, role_attr))
        response = client.patch(f"{API}/organizations/{tenant_a.org.id}/", {"name": "Renamed"}, format="json")
        assert response.status_code == expected

    @pytest.mark.parametrize(
        ("role_attr", "expected"),
        [("owner", 200), ("admin", 200), ("ws_agent", 403), ("ws_viewer", 403)],
    )
    def test_workspace_update_permission(self, client_for, tenant_a, role_attr, expected):
        client = client_for(getattr(tenant_a, role_attr))
        response = client.patch(f"{API}/workspaces/{tenant_a.workspace.id}/", {"name": "X"}, format="json")
        assert response.status_code == expected

    def test_viewer_can_read_workspace_but_not_manage_members(self, client_for, tenant_a):
        client = client_for(tenant_a.ws_viewer)
        assert client.get(f"{API}/workspaces/{tenant_a.workspace.id}/").status_code == 200
        assert client.get(f"{API}/workspaces/{tenant_a.workspace.id}/members/").status_code == 200
        response = client.post(
            f"{API}/workspaces/{tenant_a.workspace.id}/members/",
            {"user_id": str(tenant_a.member.id), "role": "admin"},
            format="json",
        )
        assert response.status_code == 403

    def test_workspace_supervisor_cannot_escalate_self(self, client_for, tenant_a):
        user = UserFactory()
        from tests.factories import OrganizationMembershipFactory

        OrganizationMembershipFactory(organization=tenant_a.org, user=user)
        membership = WorkspaceMembershipFactory(workspace=tenant_a.workspace, user=user, role=WorkspaceRole.SUPERVISOR)
        response = client_for(user).patch(
            f"{API}/workspaces/{tenant_a.workspace.id}/members/{membership.id}/", {"role": "admin"}, format="json"
        )
        assert response.status_code == 403
        membership.refresh_from_db()
        assert membership.role == WorkspaceRole.SUPERVISOR

    def test_member_cannot_read_audit_logs(self, client_for, tenant_a):
        assert client_for(tenant_a.member).get(f"{API}/organizations/{tenant_a.org.id}/audit-logs/").status_code == 403
