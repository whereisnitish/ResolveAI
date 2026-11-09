from __future__ import annotations

import re
from datetime import timedelta

from django.core import mail
from django.utils import timezone

from apps.organizations.models import Invitation, InvitationStatus, OrganizationMembership
from apps.organizations.services import hash_token
from apps.workspaces.models import WorkspaceMembership
from common.rbac import OrganizationRole, WorkspaceRole
from tests.conftest import Tenant
from tests.factories import DEFAULT_PASSWORD, InvitationFactory, UserFactory

API = "/api/v1"


def _invite(client, tenant: Tenant, **data):  # type: ignore[no-untyped-def]
    payload = {"email": "new.hire@example.com", "role": "member", **data}
    return client.post(f"{API}/organizations/{tenant.org.id}/invitations/", payload, format="json")


def _raw_token() -> str:
    match = re.search(r"invite\?token=(\S+)", mail.outbox[-1].body)
    assert match
    return match.group(1)


class TestOrganizationCrud:
    def test_create_additional_org_makes_caller_owner(self, client_for, tenant_a):
        client = client_for(tenant_a.member)
        response = client.post(f"{API}/organizations/", {"name": "Side Project"}, format="json")
        assert response.status_code == 201
        assert response.json()["role"] == "owner"
        me = client.get(f"{API}/auth/me/").json()
        assert {o["name"] for o in me["organizations"]} == {"Acme", "Side Project"}

    def test_update(self, client_for, tenant_a):
        response = client_for(tenant_a.owner).patch(
            f"{API}/organizations/{tenant_a.org.id}/", {"name": "Acme Inc", "country": "us"}, format="json"
        )
        assert response.status_code == 200
        assert response.json()["name"] == "Acme Inc" and response.json()["country"] == "US"


class TestInvitations:
    def test_full_flow_existing_user(self, client_for, tenant_a, django_capture_on_commit_callbacks):
        invitee = UserFactory(email="new.hire@example.com")
        with django_capture_on_commit_callbacks(execute=True):
            response = _invite(
                client_for(tenant_a.admin), tenant_a, workspace=str(tenant_a.workspace.id), workspace_role="agent"
            )
        assert response.status_code == 201
        token = _raw_token()
        invitation = Invitation.objects.get()
        assert invitation.token_hash == hash_token(token) and token not in invitation.token_hash

        preview = client_for(invitee).post(f"{API}/invitations/preview/", {"token": token}, format="json")
        assert preview.status_code == 200 and preview.json()["organization_name"] == "Acme"

        response = client_for(invitee).post(f"{API}/invitations/accept/", {"token": token}, format="json")
        assert response.status_code == 200
        assert OrganizationMembership.objects.get(organization=tenant_a.org, user=invitee).role == "member"
        assert WorkspaceMembership.objects.get(workspace=tenant_a.workspace, user=invitee).role == "agent"
        invitation.refresh_from_db()
        assert invitation.status == InvitationStatus.ACCEPTED
        # Single use
        again = client_for(invitee).post(f"{API}/invitations/accept/", {"token": token}, format="json")
        assert again.status_code == 400

    def test_register_with_invitation_joins_org_without_creating_one(
        self, api_client, client_for, tenant_a, django_capture_on_commit_callbacks
    ):
        with django_capture_on_commit_callbacks(execute=True):
            _invite(client_for(tenant_a.owner), tenant_a, role="admin")
        token = _raw_token()
        response = api_client.post(
            f"{API}/auth/register/",
            {
                "email": "new.hire@example.com",
                "password": "a-Very-strong-passw0rd",
                "full_name": "N",
                "invitation_token": token,
            },
            format="json",
        )
        assert response.status_code == 201, response.json()
        body = response.json()
        assert [o["id"] for o in body["organizations"]] == [str(tenant_a.org.id)]
        assert body["organizations"][0]["role"] == "admin"
        assert body["user"]["email_verified"] is True

    def test_email_mismatch_rejected(self, client_for, tenant_a, django_capture_on_commit_callbacks):
        with django_capture_on_commit_callbacks(execute=True):
            _invite(client_for(tenant_a.owner), tenant_a)
        response = client_for(UserFactory(email="someone.else@example.com")).post(
            f"{API}/invitations/accept/", {"token": _raw_token()}, format="json"
        )
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "invitation_email_mismatch"

    def test_expired_and_revoked_invitations_unusable(self, client_for, tenant_a):
        user = UserFactory(email="late@example.com")
        InvitationFactory(
            organization=tenant_a.org,
            email=user.email,
            token_hash=hash_token("expired"),
            expires_at=timezone.now() - timedelta(seconds=1),
        )
        client = client_for(user)
        assert client.post(f"{API}/invitations/accept/", {"token": "expired"}, format="json").status_code == 400
        assert client.post(f"{API}/invitations/preview/", {"token": "expired"}, format="json").status_code == 404

        inv = InvitationFactory(organization=tenant_a.org, email="r@example.com", token_hash=hash_token("revoke-me"))
        url = f"{API}/organizations/{tenant_a.org.id}/invitations/{inv.id}/revoke/"
        assert client_for(tenant_a.owner).post(url).status_code == 200
        assert client_for(tenant_a.owner).post(url).status_code == 409

    def test_duplicate_pending_and_existing_member_rejected(self, client_for, tenant_a):
        client = client_for(tenant_a.owner)
        assert _invite(client, tenant_a).status_code == 201
        assert _invite(client, tenant_a).json()["error"]["code"] == "invitation_exists"
        assert _invite(client, tenant_a, email=tenant_a.member.email).json()["error"]["code"] == "already_member"

    def test_admin_cannot_invite_owner(self, client_for, tenant_a):
        response = _invite(client_for(tenant_a.admin), tenant_a, role="owner")
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "role_not_assignable"

    def test_member_cannot_invite(self, client_for, tenant_a):
        assert _invite(client_for(tenant_a.member), tenant_a).status_code == 403


class TestMemberManagement:
    def _url(self, tenant: Tenant, user) -> str:  # type: ignore[no-untyped-def]
        return f"{API}/organizations/{tenant.org.id}/members/{tenant.membership(user).id}/"

    def test_cannot_demote_or_deactivate_last_owner(self, client_for, tenant_a):
        client = client_for(tenant_a.owner)
        url = self._url(tenant_a, tenant_a.owner)
        assert client.patch(url, {"role": "admin"}, format="json").json()["error"]["code"] == "last_owner"
        assert client.patch(url, {"is_active": False}, format="json").status_code == 409
        assert client.delete(url).status_code == 409

    def test_owner_can_step_down_when_another_owner_exists(self, client_for, tenant_a):
        client = client_for(tenant_a.owner)
        assert client.patch(self._url(tenant_a, tenant_a.admin), {"role": "owner"}, format="json").status_code == 200
        assert client.patch(self._url(tenant_a, tenant_a.owner), {"role": "admin"}, format="json").status_code == 200

    def test_admin_cannot_modify_owner_or_promote_to_owner(self, client_for, tenant_a):
        client = client_for(tenant_a.admin)
        response = client.patch(self._url(tenant_a, tenant_a.owner), {"role": "member"}, format="json")
        assert response.json()["error"]["code"] == "owner_protected"
        response = client.patch(self._url(tenant_a, tenant_a.member), {"role": "owner"}, format="json")
        assert response.json()["error"]["code"] == "role_not_assignable"
        assert client.patch(self._url(tenant_a, tenant_a.member), {"role": "admin"}, format="json").status_code == 200

    def test_remove_member_also_removes_workspace_memberships(self, client_for, tenant_a):
        response = client_for(tenant_a.owner).delete(self._url(tenant_a, tenant_a.ws_agent))
        assert response.status_code == 204
        assert not WorkspaceMembership.objects.filter(user=tenant_a.ws_agent).exists()
        assert client_for(tenant_a.ws_agent).get(f"{API}/workspaces/{tenant_a.workspace.id}/").status_code == 404

    def test_member_list(self, client_for, tenant_a):
        response = client_for(tenant_a.member).get(f"{API}/organizations/{tenant_a.org.id}/members/")
        assert response.status_code == 403  # members can't list members
        response = client_for(tenant_a.billing_admin).get(f"{API}/organizations/{tenant_a.org.id}/members/?search=")
        assert response.json()["count"] == 6


class TestAuditTrail:
    def test_role_change_is_audited(self, client_for, tenant_a):
        client = client_for(tenant_a.owner)
        client.patch(
            f"{API}/organizations/{tenant_a.org.id}/members/{tenant_a.membership(tenant_a.member).id}/",
            {"role": "admin"},
            format="json",
        )
        logs = client.get(f"{API}/organizations/{tenant_a.org.id}/audit-logs/?action=organization.member_updated")
        entry = logs.json()["results"][0]
        assert entry["actor_email"] == tenant_a.owner.email
        assert entry["metadata"]["role"] == OrganizationRole.ADMIN


def test_login_via_password_works_for_factory_users(api_client, tenant_a):
    response = api_client.post(
        f"{API}/auth/login/", {"email": tenant_a.ws_agent.email, "password": DEFAULT_PASSWORD}, format="json"
    )
    assert response.status_code == 200
    assert response.json()["workspaces"][0]["role"] == WorkspaceRole.AGENT
