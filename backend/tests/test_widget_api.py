"""Public widget API: visitor auth, isolation (critical test #4), origins, CORS, privacy."""

from __future__ import annotations

from django.core import signing
from django.core.files.uploadedfile import SimpleUploadedFile
from freezegun import freeze_time
from rest_framework.test import APIClient

from apps.conversations.models import Conversation
from apps.conversations.services import Actor, post_message
from apps.customers.models import Customer, CustomerIdentity
from apps.widget.auth import TOKEN_SALT
from apps.widget.models import WidgetSettings
from tests.factories import make_conversation

W = "/api/v1/widget"
SITE = "https://shop.example.com"


def start_session(workspace, visitor_token=None, origin=SITE):  # type: ignore[no-untyped-def]
    client = APIClient()
    payload = {"workspace_id": workspace.public_id, "page_url": f"{SITE}/pricing"}
    if visitor_token:
        payload["visitor_token"] = visitor_token
    headers = {"HTTP_ORIGIN": origin} if origin else {}
    response = client.post(f"{W}/session/", payload, format="json", **headers)
    return client, response


def visitor(workspace, origin=SITE):  # type: ignore[no-untyped-def]
    client, response = start_session(workspace, origin=origin)
    assert response.status_code == 200, response.json()
    body = response.json()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {body['session_token']}", HTTP_ORIGIN=origin)
    return client, body


class TestSession:
    def test_new_visitor_session(self, tenant_a):
        _client, response = start_session(tenant_a.workspace)
        assert response.status_code == 200
        body = response.json()
        assert set(body) == {"session_token", "expires_in", "visitor_token", "visitor", "settings"}
        assert body["settings"]["team_name"] == tenant_a.workspace.name
        assert set(body["settings"]) == set(WidgetSettings.PUBLIC_FIELDS)
        customer = Customer.objects.get(workspace=tenant_a.workspace)
        assert customer.is_anonymous and customer.last_seen_url == f"{SITE}/pricing"
        identity = CustomerIdentity.objects.get(customer=customer)
        assert body["visitor_token"] not in identity.value_hash  # only the hash is stored

    def test_returning_visitor_keeps_identity(self, tenant_a):
        _, first = start_session(tenant_a.workspace)
        _, second = start_session(tenant_a.workspace, visitor_token=first.json()["visitor_token"])
        assert second.json()["visitor_token"] == first.json()["visitor_token"]
        assert Customer.objects.filter(workspace=tenant_a.workspace).count() == 1

    def test_visitor_token_from_other_workspace_starts_fresh(self, tenant_a, tenant_b):
        _, a = start_session(tenant_a.workspace)
        _, b = start_session(tenant_b.workspace, visitor_token=a.json()["visitor_token"])
        assert b.json()["visitor_token"] != a.json()["visitor_token"]
        assert Customer.objects.filter(workspace=tenant_b.workspace).count() == 1

    def test_unknown_disabled_and_archived_workspaces(self, tenant_a):
        client = APIClient()
        assert client.post(f"{W}/session/", {"workspace_id": "ws_nope"}, format="json").status_code == 404
        WidgetSettings.objects.update_or_create(workspace=tenant_a.workspace, defaults={"enabled": False})
        assert start_session(tenant_a.workspace)[1].status_code == 404

    def test_origin_allowlist(self, tenant_a):
        WidgetSettings.objects.update_or_create(workspace=tenant_a.workspace, defaults={"allowed_origins": [SITE]})
        assert start_session(tenant_a.workspace, origin=SITE)[1].status_code == 200
        r = start_session(tenant_a.workspace, origin="https://evil.example")[1]
        assert r.status_code == 403 and r.json()["error"]["code"] == "origin_not_allowed"
        assert start_session(tenant_a.workspace, origin=None)[1].status_code == 403

    def test_session_response_never_leaks_internal_data(self, tenant_a):
        raw = start_session(tenant_a.workspace)[1].content.decode()
        for secret in (str(tenant_a.workspace.id), str(tenant_a.org.id), tenant_a.owner.email, "allowed_origins"):
            assert secret not in raw


class TestVisitorConversations:
    def test_full_visitor_flow(self, tenant_a):
        client, _ = visitor(tenant_a.workspace)
        r = client.post(f"{W}/conversations/", {"body": "Do you ship to Pune?"}, format="json")
        assert r.status_code == 201, r.json()
        conv_id = r.json()["id"]
        conv = Conversation.objects.get(id=conv_id)
        assert conv.channel == "widget" and conv.customer.workspace == tenant_a.workspace

        post_message(conversation=conv, actor=Actor.agent(tenant_a.ws_agent), body="Yes, we do!")
        post_message(conversation=conv, actor=Actor.agent(tenant_a.ws_agent), body="VIP - be nice", kind="note")
        client.post(f"{W}/conversations/{conv_id}/messages/", {"body": "Great, thanks"}, format="json")

        msgs = client.get(f"{W}/conversations/{conv_id}/messages/").json()
        assert [m["body"] for m in msgs] == ["Do you ship to Pune?", "Yes, we do!", "Great, thanks"]
        agent_msg = msgs[1]
        assert agent_msg["author_name"] == tenant_a.ws_agent.get_short_name()
        assert tenant_a.ws_agent.email not in str(msgs)
        assert [c["id"] for c in client.get(f"{W}/conversations/").json()] == [conv_id]

    def test_visitor_cannot_read_another_visitors_conversation_same_workspace(self, tenant_a):
        alice, _ = visitor(tenant_a.workspace)
        bob, _ = visitor(tenant_a.workspace)
        conv_id = alice.post(f"{W}/conversations/", {"body": "private"}, format="json").json()["id"]
        assert bob.get(f"{W}/conversations/{conv_id}/messages/").status_code == 404
        assert bob.post(f"{W}/conversations/{conv_id}/messages/", {"body": "x"}, format="json").status_code == 404
        assert bob.get(f"{W}/conversations/").json() == []

    def test_widget_token_cannot_access_another_workspace(self, tenant_a, tenant_b):
        """Critical security test #4."""
        a_client, _ = visitor(tenant_a.workspace)
        b_conv = make_conversation(tenant_b.workspace)
        assert a_client.get(f"{W}/conversations/{b_conv.id}/messages/").status_code == 404
        assert (
            a_client.post(f"{W}/conversations/{b_conv.id}/messages/", {"body": "x"}, format="json").status_code == 404
        )
        a_client.post(f"{W}/conversations/", {"body": "mine"}, format="json")
        assert Conversation.objects.filter(workspace=tenant_b.workspace).count() == 1

    def test_forged_token_payload_rejected(self, tenant_a, tenant_b):
        client, body = visitor(tenant_a.workspace)
        b_identity = CustomerIdentity.objects.create(
            workspace=tenant_b.workspace,
            customer=make_conversation(tenant_b.workspace).customer,
            kind="visitor",
            value_hash="x" * 64,
        )
        # Mixing a valid identity from B with workspace A's id must fail even with a valid signature.
        mixed = signing.dumps(
            {"w": str(tenant_a.workspace.id), "c": str(b_identity.customer_id), "i": str(b_identity.id)},
            salt=TOKEN_SALT,
        )
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {mixed}", HTTP_ORIGIN=SITE)
        assert client.get(f"{W}/conversations/").status_code == 401
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {body['session_token']}x", HTTP_ORIGIN=SITE)
        assert client.get(f"{W}/conversations/").status_code == 401
        unsalted = signing.dumps({"w": str(tenant_a.workspace.id), "c": "x", "i": "y"})
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {unsalted}", HTTP_ORIGIN=SITE)
        assert client.get(f"{W}/conversations/").status_code == 401

    def test_session_token_expires(self, tenant_a):
        with freeze_time("2026-01-01 10:00:00"):
            client, _ = visitor(tenant_a.workspace)
        with freeze_time("2026-01-01 10:59:00"):
            assert client.get(f"{W}/conversations/").status_code == 200
        with freeze_time("2026-01-01 11:01:00"):
            r = client.get(f"{W}/conversations/")
            assert r.status_code == 401 and r.json()["error"]["code"] == "widget_session_invalid"

    def test_disabling_widget_or_origin_change_revokes_live_sessions(self, tenant_a):
        client, _ = visitor(tenant_a.workspace)
        WidgetSettings.objects.filter(workspace=tenant_a.workspace).update(allowed_origins=["https://other.example"])
        assert client.get(f"{W}/conversations/").status_code == 403
        WidgetSettings.objects.filter(workspace=tenant_a.workspace).update(allowed_origins=[], enabled=False)
        assert client.get(f"{W}/conversations/").status_code == 403

    def test_unauthenticated_requests(self, tenant_a):
        client = APIClient()
        assert client.get(f"{W}/conversations/").status_code == 401
        assert client.post(f"{W}/identify/", {"name": "x"}, format="json").status_code == 401

    def test_message_validation(self, tenant_a):
        client, _ = visitor(tenant_a.workspace)
        assert client.post(f"{W}/conversations/", {"body": ""}, format="json").status_code == 400
        assert client.post(f"{W}/conversations/", {"body": "x" * 5001}, format="json").status_code == 400
        assert client.post(f"{W}/conversations/", {"body": None}, format="json").status_code == 400

    def test_html_is_stored_verbatim_not_rendered(self, tenant_a):
        client, _ = visitor(tenant_a.workspace)
        payload = "<img src=x onerror=alert(1)>"
        conv_id = client.post(f"{W}/conversations/", {"body": payload}, format="json").json()["id"]
        assert client.get(f"{W}/conversations/{conv_id}/messages/").json()[0]["body"] == payload


class TestIdentify:
    def test_identify_updates_only_own_record_never_merges(self, tenant_a):
        existing = Customer.objects.create(workspace=tenant_a.workspace, name="Real CEO", email="ceo@acme.com")
        existing_conv = make_conversation(tenant_a.workspace, existing, body="board secrets")
        client, _ = visitor(tenant_a.workspace)
        r = client.post(f"{W}/identify/", {"name": "Imposter", "email": "CEO@acme.com"}, format="json")
        assert r.status_code == 200 and r.json()["visitor"] == {"name": "Imposter", "email": "ceo@acme.com"}
        assert Customer.objects.filter(workspace=tenant_a.workspace, email="ceo@acme.com").count() == 2
        existing.refresh_from_db()
        assert existing.name == "Real CEO"
        assert client.get(f"{W}/conversations/").json() == []
        assert client.get(f"{W}/conversations/{existing_conv.id}/messages/").status_code == 404

    def test_identify_marks_visitor_identified(self, tenant_a):
        client, _ = visitor(tenant_a.workspace)
        client.post(f"{W}/identify/", {"email": "lead@example.com"}, format="json")
        customer = Customer.objects.get(workspace=tenant_a.workspace)
        assert not customer.is_anonymous and customer.email == "lead@example.com"
        assert client.post(f"{W}/identify/", {"email": "not-an-email"}, format="json").status_code == 400


class TestWidgetAttachments:
    PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16

    def _agent_upload(self, client_for, tenant, conv, kind="reply"):  # type: ignore[no-untyped-def]
        r = client_for(tenant.ws_agent).post(
            f"/api/v1/workspaces/{tenant.workspace.id}/conversations/{conv.id}/messages/",
            {"body": "file", "kind": kind, "files": [SimpleUploadedFile("x.png", self.PNG)]},
        )
        assert r.status_code == 201, r.json()
        return r.json()["attachments"][0]["id"]

    def test_visitor_downloads_own_reply_attachment_only(self, client_for, tenant_a):
        client, _ = visitor(tenant_a.workspace)
        conv = Conversation.objects.get(
            id=client.post(f"{W}/conversations/", {"body": "hi"}, format="json").json()["id"]
        )
        reply_att = self._agent_upload(client_for, tenant_a, conv)
        note_att = self._agent_upload(client_for, tenant_a, conv, kind="note")
        assert client.get(f"{W}/attachments/{reply_att}/").status_code == 200
        assert client.get(f"{W}/attachments/{note_att}/").status_code == 404
        other, _ = visitor(tenant_a.workspace)
        assert other.get(f"{W}/attachments/{reply_att}/").status_code == 404


class TestCorsAndCsrf:
    def test_preflight_allows_any_origin_without_credentials(self):
        r = APIClient().options(
            f"{W}/session/", HTTP_ORIGIN="https://random.example", HTTP_ACCESS_CONTROL_REQUEST_METHOD="POST"
        )
        assert r.status_code == 204
        assert r["Access-Control-Allow-Origin"] == "https://random.example"
        assert "Access-Control-Allow-Credentials" not in r
        assert "authorization" in r["Access-Control-Allow-Headers"]

    def test_dashboard_api_does_not_get_widget_cors(self, client_for, tenant_a):
        r = client_for(tenant_a.owner).get("/api/v1/auth/me/", HTTP_ORIGIN="https://random.example")
        assert r.get("Access-Control-Allow-Origin") is None

    def test_widget_api_does_not_require_csrf(self, tenant_a):
        client = APIClient(enforce_csrf_checks=True)
        r = client.post(
            f"{W}/session/", {"workspace_id": tenant_a.workspace.public_id}, format="json", HTTP_ORIGIN=SITE
        )
        assert r.status_code == 200

    def test_widget_ignores_dashboard_session_cookie(self, client_for, tenant_a):
        """A logged-in agent's cookie must not authenticate widget calls."""
        assert client_for(tenant_a.owner).get(f"{W}/conversations/").status_code == 401


class TestRateLimit:
    def test_session_rate_limited_per_ip(self, tenant_a, settings):
        from rest_framework.throttling import SimpleRateThrottle

        rates = {**settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"], "widget_session": "3/min"}
        original = SimpleRateThrottle.THROTTLE_RATES
        SimpleRateThrottle.THROTTLE_RATES = rates
        try:
            codes = [start_session(tenant_a.workspace)[1].status_code for _ in range(4)]
        finally:
            SimpleRateThrottle.THROTTLE_RATES = original
        assert codes == [200, 200, 200, 429]


class TestWidgetSettingsAdmin:
    def test_admin_updates_settings_and_validation(self, client_for, tenant_a):
        url = f"/api/v1/workspaces/{tenant_a.workspace.id}/widget-settings/"
        client = client_for(tenant_a.owner)
        r = client.patch(
            url,
            {"allowed_origins": ["https://Shop.Example.com/", "http://localhost:5173"], "brand_color": "#112233"},
            format="json",
        )
        assert r.status_code == 200
        assert r.json()["allowed_origins"] == ["https://shop.example.com", "http://localhost:5173"]
        assert client.patch(url, {"allowed_origins": ["javascript:alert(1)"]}, format="json").status_code == 400
        assert client.patch(url, {"allowed_origins": ["https://x.com/path"]}, format="json").status_code == 400
        assert client.patch(url, {"brand_color": "red"}, format="json").status_code == 400
        assert client_for(tenant_a.ws_agent).patch(url, {"enabled": False}, format="json").status_code == 403
