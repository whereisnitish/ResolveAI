from __future__ import annotations

import re

import pytest
from django.core import mail
from django.test import override_settings
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.organizations.models import Organization, OrganizationMembership
from apps.workspaces.models import Workspace, WorkspaceMembership
from common.rbac import OrganizationRole, WorkspaceRole
from tests.factories import DEFAULT_PASSWORD, UserFactory

API = "/api/v1/auth"

REGISTRATION = {
    "email": "Founder@Example.com",
    "password": "a-Very-strong-passw0rd",
    "full_name": "Asha Founder",
    "organization_name": "Acme Support",
    "country": "in",
}


def _register(client: APIClient, **overrides: str):  # type: ignore[no-untyped-def]
    return client.post(f"{API}/register/", {**REGISTRATION, **overrides}, format="json")


class TestRegistration:
    def test_creates_user_org_default_workspace_and_owner(self, api_client, django_capture_on_commit_callbacks):
        with django_capture_on_commit_callbacks(execute=True):
            response = _register(api_client)
        assert response.status_code == 201, response.json()

        user = User.objects.get(email="founder@example.com")  # normalized
        org = Organization.objects.get()
        workspace = Workspace.objects.get()
        assert org.name == "Acme Support" and org.country == "IN" and org.created_by == user
        assert workspace.organization == org and workspace.is_default
        assert OrganizationMembership.objects.get(organization=org, user=user).role == OrganizationRole.OWNER
        assert WorkspaceMembership.objects.get(workspace=workspace, user=user).role == WorkspaceRole.ADMIN
        assert not user.is_email_verified

        body = response.json()
        assert body["user"]["email"] == "founder@example.com"
        assert body["organizations"][0]["role"] == "owner"
        assert body["workspaces"][0]["id"] == str(workspace.id)
        assert "workspace.update" in body["workspaces"][0]["permissions"]

        # Registration logs the user in via an HttpOnly session cookie.
        cookie = response.cookies["resolveai_session"]
        assert cookie["httponly"]
        assert api_client.get(f"{API}/me/").status_code == 200

        # Verification email was queued and sent after commit.
        assert len(mail.outbox) == 1
        assert "/verify-email?token=" in mail.outbox[0].body
        assert AuditLog.objects.filter(action="user.registered", actor=user).exists()

    def test_duplicate_email_is_rejected_case_insensitively(self, api_client):
        UserFactory(email="founder@example.com")
        response = _register(api_client, email="FOUNDER@example.com")
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "email_taken"
        assert Organization.objects.count() == 0

    @pytest.mark.parametrize("password", ["short", "password123", "1234567890123"])
    def test_weak_passwords_rejected(self, api_client, password):
        response = _register(api_client, password=password)
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "validation_error"
        assert not User.objects.exists()

    def test_organization_name_required_without_invitation(self, api_client):
        response = _register(api_client, organization_name="")
        assert response.status_code == 400
        assert "organization_name" in response.json()["error"]["details"]

    def test_registration_is_atomic(self, api_client, monkeypatch):
        from apps.organizations import services as org_services

        def boom(**kwargs):  # type: ignore[no-untyped-def]
            raise RuntimeError("workspace creation failed")

        monkeypatch.setattr(org_services, "create_workspace", boom)
        client = APIClient(raise_request_exception=False)
        response = _register(client)
        assert response.status_code == 500
        assert response.json()["error"]["code"] == "server_error"
        assert "workspace creation failed" not in response.content.decode()
        assert not User.objects.exists() and not Organization.objects.exists()


class TestLoginLogout:
    def test_login_success_returns_me_and_rotates_session(self, api_client):
        user = UserFactory(email="agent@example.com")
        api_client.cookies["resolveai_session"] = "attacker-fixed-session"
        response = api_client.post(
            f"{API}/login/", {"email": "AGENT@example.com", "password": DEFAULT_PASSWORD}, format="json"
        )
        assert response.status_code == 200
        assert response.json()["user"]["id"] == str(user.id)
        assert response.cookies["resolveai_session"].value != "attacker-fixed-session"
        assert AuditLog.objects.filter(action="user.login", actor=user).exists()

    def test_wrong_password_generic_error_and_audited(self, api_client):
        UserFactory(email="agent@example.com")
        response = api_client.post(f"{API}/login/", {"email": "agent@example.com", "password": "nope"}, format="json")
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "invalid_credentials"
        unknown = api_client.post(f"{API}/login/", {"email": "ghost@example.com", "password": "nope"}, format="json")
        assert unknown.json()["error"] == {
            **response.json()["error"],
            "request_id": unknown.json()["error"]["request_id"],
        }
        assert AuditLog.objects.filter(action="user.login_failed").count() == 2

    def test_inactive_user_cannot_login(self, api_client):
        UserFactory(email="gone@example.com", is_active=False)
        response = api_client.post(
            f"{API}/login/", {"email": "gone@example.com", "password": DEFAULT_PASSWORD}, format="json"
        )
        assert response.status_code == 400

    def test_logout_ends_session(self, client_for):
        client = client_for(UserFactory())
        assert client.post(f"{API}/logout/").status_code == 204
        assert client.get(f"{API}/me/").status_code == 403


class TestCsrf:
    def test_login_requires_csrf_token(self, csrf_client):
        UserFactory(email="agent@example.com")
        payload = {"email": "agent@example.com", "password": DEFAULT_PASSWORD}
        response = csrf_client.post(f"{API}/login/", payload, format="json")
        assert response.status_code == 403
        assert "CSRF" in response.json()["error"]["message"]

        token = csrf_client.get(f"{API}/csrf/").json()["csrf_token"]
        response = csrf_client.post(f"{API}/login/", payload, format="json", HTTP_X_CSRFTOKEN=token)
        assert response.status_code == 200

    def test_authenticated_unsafe_request_requires_csrf(self, tenant_a):
        client = APIClient(enforce_csrf_checks=True)
        client.force_login(tenant_a.owner)
        response = client.patch(f"/api/v1/organizations/{tenant_a.org.id}/", {"name": "X"}, format="json")
        assert response.status_code == 403

    def test_register_requires_csrf(self, csrf_client):
        assert _register(csrf_client).status_code == 403
        assert not User.objects.exists()


class TestEmailVerification:
    def _token_from_outbox(self) -> str:
        match = re.search(r"verify-email\?token=(\S+)", mail.outbox[-1].body)
        assert match
        return match.group(1)

    def test_full_flow(self, api_client, django_capture_on_commit_callbacks):
        with django_capture_on_commit_callbacks(execute=True):
            _register(api_client)
        token = self._token_from_outbox()
        response = api_client.post(f"{API}/verify-email/", {"token": token}, format="json")
        assert response.status_code == 200
        assert User.objects.get().is_email_verified
        # Idempotent
        assert api_client.post(f"{API}/verify-email/", {"token": token}, format="json").status_code == 200

    def test_tampered_token_rejected(self, api_client):
        response = api_client.post(f"{API}/verify-email/", {"token": "abc:def"}, format="json")
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "token_invalid"

    def test_token_bound_to_email(self, api_client):
        from apps.accounts.services import make_email_verification_token

        user = UserFactory(email_verified_at=None)
        token = make_email_verification_token(user)
        user.email = "changed@example.com"
        user.save()
        response = api_client.post(f"{API}/verify-email/", {"token": token}, format="json")
        assert response.status_code == 400

    @override_settings(EMAIL_VERIFICATION_MAX_AGE_SECONDS=-1)
    def test_expired_token_rejected(self, api_client):
        from apps.accounts.services import make_email_verification_token

        token = make_email_verification_token(UserFactory(email_verified_at=None))
        response = api_client.post(f"{API}/verify-email/", {"token": token}, format="json")
        assert response.json()["error"]["code"] == "token_expired"

    def test_resend(self, client_for, django_capture_on_commit_callbacks):
        client = client_for(UserFactory(email_verified_at=None))
        with django_capture_on_commit_callbacks(execute=True):
            assert client.post(f"{API}/verify-email/resend/").status_code == 202
        assert len(mail.outbox) == 1


class TestPasswordReset:
    def test_full_flow_and_old_sessions_invalidated(self, api_client, client_for, django_capture_on_commit_callbacks):
        user = UserFactory(email="agent@example.com")
        other_session = client_for(user)
        assert other_session.get(f"{API}/me/").status_code == 200

        with django_capture_on_commit_callbacks(execute=True):
            response = api_client.post(f"{API}/password-reset/", {"email": "agent@example.com"}, format="json")
        assert response.status_code == 202
        match = re.search(r"uid=([^&\s]+)&token=(\S+)", mail.outbox[0].body)
        assert match
        uid, token = match.groups()

        new_password = "Brand-new-passw0rd!"
        payload = {"uid": uid, "token": token, "new_password": new_password}
        assert api_client.post(f"{API}/password-reset/confirm/", payload, format="json").status_code == 200
        # Single use
        assert api_client.post(f"{API}/password-reset/confirm/", payload, format="json").status_code == 400

        assert other_session.get(f"{API}/me/").status_code == 403
        login = api_client.post(f"{API}/login/", {"email": user.email, "password": new_password}, format="json")
        assert login.status_code == 200

    def test_unknown_email_gives_same_response_no_email(self, api_client, django_capture_on_commit_callbacks):
        with django_capture_on_commit_callbacks(execute=True):
            response = api_client.post(f"{API}/password-reset/", {"email": "ghost@example.com"}, format="json")
        assert response.status_code == 202
        assert len(mail.outbox) == 0

    def test_garbage_uid_rejected(self, api_client):
        payload = {"uid": "!!!", "token": "x", "new_password": "Brand-new-passw0rd!"}
        assert api_client.post(f"{API}/password-reset/confirm/", payload, format="json").status_code == 400


class TestPasswordChange:
    def test_change_keeps_current_session_and_kills_others(self, client_for):
        user = UserFactory()
        current, other = client_for(user), client_for(user)
        response = current.post(
            f"{API}/password/change/",
            {"current_password": DEFAULT_PASSWORD, "new_password": "Another-strong-pw1"},
            format="json",
        )
        assert response.status_code == 200
        assert current.get(f"{API}/me/").status_code == 200
        assert other.get(f"{API}/me/").status_code == 403

    def test_wrong_current_password(self, client_for):
        response = client_for(UserFactory()).post(
            f"{API}/password/change/",
            {"current_password": "wrong", "new_password": "Another-strong-pw1"},
            format="json",
        )
        assert response.status_code == 400


class TestMe:
    def test_profile_update_cannot_change_email(self, client_for):
        user = UserFactory(email="me@example.com")
        response = client_for(user).patch(
            f"{API}/me/", {"full_name": "New Name", "email": "evil@example.com"}, format="json"
        )
        assert response.status_code == 200
        user.refresh_from_db()
        assert user.full_name == "New Name" and user.email == "me@example.com"


class TestThrottling:
    def test_login_is_rate_limited(self, api_client, settings):
        settings.REST_FRAMEWORK = {
            **settings.REST_FRAMEWORK,
            "DEFAULT_THROTTLE_RATES": {**settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"], "auth": "3/min"},
        }
        from rest_framework.throttling import SimpleRateThrottle

        original = SimpleRateThrottle.THROTTLE_RATES
        SimpleRateThrottle.THROTTLE_RATES = settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]
        try:
            codes = [
                api_client.post(f"{API}/login/", {"email": "a@example.com", "password": "x"}, format="json").status_code
                for _ in range(4)
            ]
        finally:
            SimpleRateThrottle.THROTTLE_RATES = original
        assert codes[:3] == [400, 400, 400]
        assert codes[3] == 429
