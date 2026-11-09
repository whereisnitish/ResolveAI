from __future__ import annotations

import itertools

import pytest
from django.core import mail
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, transaction

from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.workspaces.models import Workspace
from common import rbac
from common.rbac import OrganizationRole, Perm, WorkspaceRole
from common.tasks import send_email_task
from tests.factories import InvitationFactory, OrganizationFactory, UserFactory, WorkspaceFactory


class TestUserModel:
    def test_email_normalized_and_case_insensitive_unique(self):
        user = User.objects.create_user(email="  MiXeD@Example.COM ", password="x")
        assert user.email == "mixed@example.com"
        with pytest.raises(IntegrityError), transaction.atomic():
            User.objects.create_user(email="mixed@EXAMPLE.com", password="x")

    def test_password_is_hashed(self):
        user = User.objects.create_user(email="h@example.com", password="plain-text-pw")
        assert user.password != "plain-text-pw" and user.check_password("plain-text-pw")

    def test_superuser(self):
        admin = User.objects.create_superuser(email="root@example.com", password="x")
        assert admin.is_staff and admin.is_superuser and admin.is_email_verified


class TestConstraints:
    def test_one_default_workspace_per_org(self):
        org = OrganizationFactory()
        WorkspaceFactory(organization=org, is_default=True)
        with pytest.raises(IntegrityError), transaction.atomic():
            WorkspaceFactory(organization=org, is_default=True)

    def test_one_pending_invitation_per_email(self):
        org = OrganizationFactory()
        InvitationFactory(organization=org, email="a@example.com")
        with pytest.raises(IntegrityError), transaction.atomic():
            InvitationFactory(organization=org, email="a@example.com")
        InvitationFactory(organization=org, email="a@example.com", status="revoked")  # allowed

    def test_invitation_workspace_role_consistency(self):
        org = OrganizationFactory()
        ws = WorkspaceFactory(organization=org)
        with pytest.raises(IntegrityError), transaction.atomic():
            InvitationFactory(organization=org, workspace=ws, workspace_role="")

    def test_workspace_public_ids_unique_and_random(self):
        ids = {WorkspaceFactory().public_id for _ in range(5)}
        assert len(ids) == 5


class TestAuditLog:
    def test_append_only(self):
        entry = AuditLog.objects.create(action="test.action")
        entry.action = "tampered"
        with pytest.raises(RuntimeError):
            entry.save()
        with pytest.raises(RuntimeError):
            entry.delete()


class TestWorkspaceOwnedModel:
    """The abstract tenant base derives org from workspace and rejects mismatches."""

    def test_mismatch_rejected(self):
        from apps.workspaces.models import WorkspaceOwnedModel

        class Probe(WorkspaceOwnedModel):
            class Meta:
                app_label = "workspaces"
                managed = False

        ws = WorkspaceFactory()
        other_org = OrganizationFactory()
        probe = Probe(workspace=ws, organization=other_org)
        with pytest.raises(ValidationError):
            probe.save()


class TestRbacInvariants:
    def test_role_hierarchy_is_monotonic(self):
        order = [WorkspaceRole.VIEWER, WorkspaceRole.AGENT, WorkspaceRole.SUPERVISOR, WorkspaceRole.ADMIN]
        perms = [rbac.workspace_permissions(r) for r in order]
        assert all(a < b for a, b in itertools.pairwise(perms))

    def test_owner_superset_of_admin(self):
        assert rbac.org_permissions(OrganizationRole.ADMIN) < rbac.org_permissions(OrganizationRole.OWNER)

    def test_only_owner_manages_ownership_and_billing(self):
        for role in OrganizationRole.values:
            has = Perm.ORG_OWNERSHIP_MANAGE in rbac.org_permissions(role)
            assert has == (role == OrganizationRole.OWNER)
        assert Perm.ORG_BILLING_MANAGE in rbac.org_permissions(OrganizationRole.BILLING_ADMIN)
        assert Perm.ORG_BILLING_MANAGE not in rbac.org_permissions(OrganizationRole.ADMIN)

    def test_every_role_has_a_permission_set(self):
        assert set(rbac.ORG_ROLE_PERMISSIONS) == set(OrganizationRole.values)
        assert set(rbac.WORKSPACE_ROLE_PERMISSIONS) == set(WorkspaceRole.values)


class TestInfrastructure:
    def test_pgvector_extension_installed(self):
        with connection.cursor() as cursor:
            cursor.execute("SELECT extname FROM pg_extension")
            extensions = {row[0] for row in cursor.fetchall()}
        assert {"vector", "citext", "pg_trgm"} <= extensions

    def test_health(self, api_client):
        response = api_client.get("/api/v1/health/")
        assert response.status_code == 200
        assert response.json() == {"status": "ok", "checks": {"database": "ok", "cache": "ok", "broker": "ok"}}
        assert response.headers["X-Request-ID"]

    def test_request_id_propagated_into_errors(self, api_client):
        response = api_client.get("/api/v1/auth/me/", HTTP_X_REQUEST_ID="abcdef12-3456")
        assert response.headers["X-Request-ID"] == "abcdef12-3456"
        assert response.json()["error"]["request_id"] == "abcdef12-3456"

    def test_invalid_request_id_replaced(self, api_client):
        response = api_client.get("/api/v1/health/", HTTP_X_REQUEST_ID="<script>")
        assert response.headers["X-Request-ID"] != "<script>"

    def test_error_envelope_shape(self, client_for):
        response = client_for(UserFactory()).post("/api/v1/organizations/", {}, format="json")
        error = response.json()["error"]
        assert response.status_code == 400
        assert set(error) == {"code", "message", "details", "request_id"}
        assert "name" in error["details"]

    def test_celery_email_task(self):
        send_email_task.delay(to="x@example.com", subject="Hi", body="Body")
        assert mail.outbox[0].to == ["x@example.com"]

    def test_openapi_schema_served(self, api_client):
        response = api_client.get("/api/v1/schema/")
        assert response.status_code == 200
        assert b"/api/v1/auth/register/" in response.content

    def test_workspace_count_baseline(self):
        assert Workspace.objects.count() == 0
        assert UserFactory().is_active


class TestClientIp:
    def _req(self, xff: str = "", remote: str = "10.0.0.9"):  # type: ignore[no-untyped-def]
        from django.test import RequestFactory

        return RequestFactory().get("/", HTTP_X_FORWARDED_FOR=xff, REMOTE_ADDR=remote)

    def test_xff_ignored_without_trusted_proxies(self, settings):
        from apps.audit.services import _client_ip

        settings.TRUSTED_PROXY_COUNT = 0
        assert _client_ip(self._req("6.6.6.6")) == "10.0.0.9"

    def test_spoofed_leftmost_entry_ignored(self, settings):
        from apps.audit.services import _client_ip

        settings.TRUSTED_PROXY_COUNT = 1
        # Client sent "6.6.6.6"; the load balancer appended the real IP.
        assert _client_ip(self._req("6.6.6.6, 203.0.113.7")) == "203.0.113.7"
