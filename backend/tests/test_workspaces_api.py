from __future__ import annotations

from apps.workspaces.models import Workspace, WorkspaceMembership
from common.rbac import WorkspaceRole
from tests.factories import OrganizationMembershipFactory, UserFactory

API = "/api/v1"


def test_admin_creates_workspace_with_unique_slug(client_for, tenant_a):
    client = client_for(tenant_a.admin)
    url = f"{API}/organizations/{tenant_a.org.id}/workspaces/"
    first = client.post(url, {"name": "EU Support", "timezone": "Europe/Berlin"}, format="json")
    second = client.post(url, {"name": "EU Support"}, format="json")
    assert first.status_code == second.status_code == 201
    assert first.json()["slug"] != second.json()["slug"]
    assert first.json()["public_id"].startswith("ws_")
    assert WorkspaceMembership.objects.get(workspace_id=first.json()["id"], user=tenant_a.admin).role == "admin"


def test_member_cannot_create_workspace(client_for, tenant_a):
    response = client_for(tenant_a.member).post(
        f"{API}/organizations/{tenant_a.org.id}/workspaces/", {"name": "Nope"}, format="json"
    )
    assert response.status_code == 403


def test_invalid_timezone_rejected(client_for, tenant_a):
    response = client_for(tenant_a.owner).patch(
        f"{API}/workspaces/{tenant_a.workspace.id}/", {"timezone": "Mars/Olympus"}, format="json"
    )
    assert response.status_code == 400


def test_update_workspace(client_for, tenant_a):
    response = client_for(tenant_a.owner).patch(
        f"{API}/workspaces/{tenant_a.workspace.id}/", {"name": "Renamed", "timezone": "Asia/Kolkata"}, format="json"
    )
    assert response.status_code == 200
    tenant_a.workspace.refresh_from_db()
    assert tenant_a.workspace.name == "Renamed" and tenant_a.workspace.timezone == "Asia/Kolkata"


def test_public_id_is_not_writable(client_for, tenant_a):
    original = tenant_a.workspace.public_id
    client_for(tenant_a.owner).patch(f"{API}/workspaces/{tenant_a.workspace.id}/", {"public_id": "ws_x"}, format="json")
    tenant_a.workspace.refresh_from_db()
    assert tenant_a.workspace.public_id == original


class TestWorkspaceMembers:
    def test_add_update_remove(self, client_for, tenant_a):
        client = client_for(tenant_a.owner)
        base = f"{API}/workspaces/{tenant_a.workspace.id}/members/"
        response = client.post(base, {"user_id": str(tenant_a.member.id), "role": "supervisor"}, format="json")
        assert response.status_code == 201
        membership_id = response.json()["id"]

        assert client.post(base, {"user_id": str(tenant_a.member.id)}, format="json").status_code == 409

        response = client.patch(f"{base}{membership_id}/", {"role": "viewer"}, format="json")
        assert response.json()["role"] == WorkspaceRole.VIEWER

        assert client.delete(f"{base}{membership_id}/").status_code == 204
        assert not WorkspaceMembership.objects.filter(id=membership_id).exists()

    def test_deactivated_org_member_cannot_be_added(self, client_for, tenant_a):
        user = UserFactory()
        OrganizationMembershipFactory(organization=tenant_a.org, user=user, is_active=False)
        response = client_for(tenant_a.owner).post(
            f"{API}/workspaces/{tenant_a.workspace.id}/members/", {"user_id": str(user.id)}, format="json"
        )
        assert response.status_code == 400

    def test_list(self, client_for, tenant_a):
        response = client_for(tenant_a.ws_agent).get(f"{API}/workspaces/{tenant_a.workspace.id}/members/")
        assert response.status_code == 200
        assert {m["user"]["email"] for m in response.json()["results"]} == {
            tenant_a.ws_agent.email,
            tenant_a.ws_viewer.email,
        }


def test_workspace_list_filter_by_org(client_for, tenant_a):
    response = client_for(tenant_a.owner).get(f"{API}/workspaces/?organization={tenant_a.org.id}")
    assert [w["id"] for w in response.json()["results"]] == [str(tenant_a.workspace.id)]
    assert Workspace.objects.count() == 1
