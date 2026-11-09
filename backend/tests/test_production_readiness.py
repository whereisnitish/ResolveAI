"""Phase 5: production hardening — DB-enforced append-only ledgers, account lockout,
probes, security headers, observability, deploy checks and N+1 guards."""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime

import pytest
from django.core.checks import run_checks
from django.db import DatabaseError, connection, transaction
from django.test import override_settings
from django.test.utils import CaptureQueriesContext

from apps.audit import services as audit
from apps.audit.models import AuditLog
from apps.billing.models import UsageLedger
from common.db import allow_purge
from common.observability import SCRUBBED, JsonFormatter, scrub_event
from tests.factories import DEFAULT_PASSWORD, CustomerFactory, TagFactory, UserFactory, make_conversation

API = "/api/v1"


def _ledger(org) -> UsageLedger:  # type: ignore[no-untyped-def]
    return UsageLedger.objects.create(
        organization=org,
        metric="conversations",
        quantity=1,
        idempotency_key=f"test:{datetime.now(UTC).timestamp()}",
        occurred_at=datetime.now(UTC),
    )


class TestAppendOnlyInDatabase:
    """The ORM guards can be bypassed (queryset.update/delete, raw SQL). The triggers can't."""

    def test_usage_ledger_rejects_update_and_delete(self, tenant_a):
        entry = _ledger(tenant_a.org)
        for attempt in (
            lambda: UsageLedger.objects.filter(pk=entry.pk).update(quantity=999),
            lambda: UsageLedger.objects.filter(pk=entry.pk).delete(),
        ):
            with pytest.raises(DatabaseError, match="append-only"), transaction.atomic():
                attempt()
        entry.refresh_from_db()
        assert entry.quantity == 1

    def test_audit_log_rejects_tampering(self, tenant_a):
        entry = audit.record("test.action", actor=tenant_a.owner, organization_id=tenant_a.org.id)
        with pytest.raises(DatabaseError, match="append-only"), transaction.atomic():
            AuditLog.objects.filter(pk=entry.pk).update(action="innocent.action")
        with pytest.raises(DatabaseError, match="append-only"), transaction.atomic(), connection.cursor() as cursor:
            cursor.execute("DELETE FROM audit_auditlog WHERE id = %s", [entry.pk])
        # Clearing actor_id alongside another column is still rejected.
        with pytest.raises(DatabaseError, match="append-only"), transaction.atomic():
            AuditLog.objects.filter(pk=entry.pk).update(actor=None, actor_email="")
        assert AuditLog.objects.get(pk=entry.pk).action == "test.action"

    def test_user_erasure_keeps_audit_trail(self):
        user = UserFactory()
        entry = audit.record("test.action", actor=user)
        user.delete()  # ON DELETE SET NULL is the one permitted update
        entry.refresh_from_db()
        assert entry.actor_id is None and entry.actor_email == user.email

    def test_purge_requires_explicit_scope(self, tenant_a):
        entry = _ledger(tenant_a.org)
        with allow_purge():
            UsageLedger.objects.filter(pk=entry.pk).delete()
        assert not UsageLedger.objects.filter(pk=entry.pk).exists()
        # The flag is transaction-local: it does not leak to later statements.
        other = _ledger(tenant_a.org)
        with pytest.raises(DatabaseError), transaction.atomic():
            UsageLedger.objects.filter(pk=other.pk).delete()


class TestLoginLockout:
    @staticmethod
    def _login(client, email: str, password: str) -> int:  # type: ignore[no-untyped-def]
        return client.post(f"{API}/auth/login/", {"email": email, "password": password}, format="json").status_code

    @override_settings(LOGIN_LOCKOUT_THRESHOLD=3)
    def test_locks_account_after_repeated_failures_even_with_right_password(self, api_client, tenant_a):
        email = tenant_a.owner.email
        for _ in range(3):
            r = api_client.post(f"{API}/auth/login/", {"email": email, "password": "wrong-password"}, format="json")
            assert r.status_code == 400
        r = api_client.post(f"{API}/auth/login/", {"email": email.upper(), "password": DEFAULT_PASSWORD}, format="json")
        assert r.status_code == 429
        assert r.json()["error"]["code"] == "login_locked"
        # Another account is unaffected (lock is per account, not global).
        r = api_client.post(
            f"{API}/auth/login/", {"email": tenant_a.admin.email, "password": DEFAULT_PASSWORD}, format="json"
        )
        assert r.status_code == 200

    @override_settings(LOGIN_LOCKOUT_THRESHOLD=3)
    def test_success_resets_counter(self, api_client, tenant_a):
        email = tenant_a.owner.email
        for _ in range(2):
            api_client.post(f"{API}/auth/login/", {"email": email, "password": "nope-nope-nope"}, format="json")
        assert self._login(api_client, email, DEFAULT_PASSWORD) == 200
        api_client.post(f"{API}/auth/logout/")
        for _ in range(2):
            api_client.post(f"{API}/auth/login/", {"email": email, "password": "nope-nope-nope"}, format="json")
        assert self._login(api_client, email, DEFAULT_PASSWORD) == 200


class TestProbesAndHeaders:
    def test_liveness_has_no_dependencies(self, api_client, monkeypatch):
        from common import views

        def boom() -> str:
            raise RuntimeError("db down")

        monkeypatch.setitem(views.READINESS_CHECKS, "database", boom)
        assert api_client.get(f"{API}/health/live/").status_code == 200
        r = api_client.get(f"{API}/health/ready/")
        assert r.status_code == 503
        assert r.json() == {"status": "degraded", "checks": {"database": "error", "cache": "ok", "broker": "ok"}}

    def test_readiness_ok(self, api_client):
        r = api_client.get(f"{API}/health/ready/")
        assert r.status_code == 200 and r.json()["status"] == "ok"

    def test_api_security_headers(self, client_for, tenant_a):
        r = client_for(tenant_a.owner).get(f"{API}/auth/me/")
        assert r.status_code == 200
        assert r["Content-Security-Policy"].startswith("default-src 'none'")
        assert r["Cache-Control"] == "no-store"
        assert r["X-Content-Type-Options"] == "nosniff"
        assert r["Cross-Origin-Resource-Policy"] == "same-site"
        assert "camera=()" in r["Permissions-Policy"]

    def test_widget_api_is_cross_origin_readable(self, api_client):
        r = api_client.get(f"{API}/widget/conversations/")
        assert r["Cross-Origin-Resource-Policy"] == "cross-origin"


class TestObservability:
    def _record(self, **extra) -> logging.LogRecord:  # type: ignore[no-untyped-def]
        record = logging.LogRecord("resolveai.test", logging.INFO, __file__, 1, "hello %s", ("world",), None)
        for k, v in extra.items():
            setattr(record, k, v)
        return record

    def test_json_formatter(self):
        line = JsonFormatter().format(self._record(route="/x/", status=200))
        payload = json.loads(line)
        assert payload["msg"] == "hello world" and payload["route"] == "/x/" and payload["status"] == 200
        assert {"ts", "level", "logger", "request_id"} <= payload.keys()

    def test_json_formatter_includes_exception(self):
        try:
            raise ValueError("bad")
        except ValueError:
            record = self._record()
            record.exc_info = sys.exc_info()
        assert "ValueError: bad" in json.loads(JsonFormatter().format(record))["exc"]

    def test_sentry_scrubber_drops_pii(self):
        event = {
            "request": {
                "data": {"password": "x"},
                "cookies": {"resolveai_session": "abc"},
                "headers": {"Authorization": "Bearer t", "X-CSRFToken": "c", "User-Agent": "ua"},
                "query_string": "token=abc",
            },
            "extra": {"nested": {"api_key": "k", "ok": 1}},
        }
        out = scrub_event(event)
        assert "data" not in out["request"] and "cookies" not in out["request"]
        assert out["request"]["headers"] == {"Authorization": SCRUBBED, "X-CSRFToken": SCRUBBED, "User-Agent": "ua"}
        assert out["request"]["query_string"] == SCRUBBED
        assert out["extra"] == {"nested": {"api_key": SCRUBBED, "ok": 1}}

    def test_access_log_uses_route_template(self, client_for, tenant_a, caplog):
        with caplog.at_level(logging.INFO, logger="resolveai.access"):
            client_for(tenant_a.owner).get(f"{API}/workspaces/{tenant_a.workspace.id}/conversations/")
        records = [r for r in caplog.records if r.name == "resolveai.access"]
        assert records, "expected an access log record"
        record = records[-1]
        assert str(tenant_a.workspace.id) not in record.route  # template, not raw path
        assert record.status == 200 and record.user_id == str(tenant_a.owner.id)


class TestDeployChecks:
    def _ids(self) -> set[str]:
        return {m.id for m in run_checks(include_deployment_checks=True) if m.id.startswith("resolveai.")}

    @override_settings(
        DEBUG=True,
        SECRET_KEY="change-me",
        ALLOWED_HOSTS=["*"],
        FRONTEND_URL="http://app.example.com",
        CSRF_TRUSTED_ORIGINS=["http://app.example.com"],
        AI_ALLOW_MOCK_FALLBACK=True,
        BILLING_ALLOW_MOCK=True,
        FIELD_ENCRYPTION_KEY="not-a-key",
    )
    def test_unsafe_config_is_blocked(self):
        ids = self._ids()
        assert {f"resolveai.E00{i}" for i in range(1, 9)} <= ids

    @override_settings(
        DEBUG=False,
        SECRET_KEY="x" * 64,
        ALLOWED_HOSTS=["app.example.com"],
        FRONTEND_URL="https://app.example.com",
        CSRF_TRUSTED_ORIGINS=["https://app.example.com"],
        AI_ALLOW_MOCK_FALLBACK=False,
        BILLING_ALLOW_MOCK=False,
        FIELD_ENCRYPTION_KEY="kJ1q0n4e3JZ0Yb9vKpXo0m6p4vR1uY5s2d8f7g6h5j4=",
    )
    def test_safe_config_has_no_errors(self):
        assert not {i for i in self._ids() if ".E" in i}


class TestNoNPlusOne:
    """List endpoints must issue the same number of queries for 2 rows as for 12."""

    def _count(self, client, url: str) -> int:  # type: ignore[no-untyped-def]
        with CaptureQueriesContext(connection) as ctx:
            assert client.get(url).status_code == 200
        return len(ctx.captured_queries)

    def test_list_endpoints_scale_flat(self, client_for, tenant_a):
        ws = tenant_a.workspace
        base = f"{API}/workspaces/{ws.id}"
        client = client_for(tenant_a.owner)
        urls = [
            f"{base}/conversations/?status=all",
            f"{base}/customers/",
            f"{base}/tags/",
            f"{API}/organizations/{tenant_a.org.id}/audit-logs/",
        ]

        def seed(n: int) -> None:
            for _ in range(n):
                conv = make_conversation(ws, customer=CustomerFactory(workspace=ws))
                conv.tags.add(TagFactory(workspace=ws))
                audit.record("test.seed", actor=tenant_a.owner, organization_id=tenant_a.org.id)

        seed(2)
        before = {u: self._count(client, u) for u in urls}
        seed(10)
        after = {u: self._count(client, u) for u in urls}
        assert after == before
