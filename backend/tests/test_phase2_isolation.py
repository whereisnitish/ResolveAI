"""Tenant isolation and RBAC for every Phase 2 workspace-scoped endpoint."""

from __future__ import annotations

import uuid

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.conversations.models import Attachment, Conversation
from tests.conftest import Tenant
from tests.factories import CustomerFactory, TagFactory, TeamFactory, make_conversation

API = "/api/v1/workspaces"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


def _resources(tenant: Tenant) -> dict[str, object]:
    ws = tenant.workspace
    customer = CustomerFactory(workspace=ws)
    conversation = make_conversation(ws, customer)
    tag = TagFactory(workspace=ws)
    team = TeamFactory(workspace=ws)
    attachment = Attachment.objects.create(
        workspace=ws,
        message=conversation.messages.first(),
        file=SimpleUploadedFile("a.png", PNG),
        filename="a.png",
        content_type="image/png",
        size=len(PNG),
    )
    return {"customer": customer, "conversation": conversation, "tag": tag, "team": team, "attachment": attachment}


def _urls(ws_id: object, r: dict[str, object]) -> list[tuple[str, str]]:
    c, cv, t, tm, a = (r[k].id for k in ("customer", "conversation", "tag", "team", "attachment"))
    base = f"{API}/{ws_id}"
    return [
        ("get", f"{base}/customers/"),
        ("post", f"{base}/customers/"),
        ("get", f"{base}/customers/{c}/"),
        ("patch", f"{base}/customers/{c}/"),
        ("delete", f"{base}/customers/{c}/"),
        ("get", f"{base}/customers/{c}/notes/"),
        ("post", f"{base}/customers/{c}/notes/"),
        ("get", f"{base}/customers/{c}/timeline/"),
        ("get", f"{base}/conversations/"),
        ("post", f"{base}/conversations/"),
        ("get", f"{base}/conversations/counts/"),
        ("get", f"{base}/conversations/{cv}/"),
        ("patch", f"{base}/conversations/{cv}/"),
        ("post", f"{base}/conversations/{cv}/assign/"),
        ("post", f"{base}/conversations/{cv}/read/"),
        ("get", f"{base}/conversations/{cv}/messages/"),
        ("post", f"{base}/conversations/{cv}/messages/"),
        ("get", f"{base}/conversations/{cv}/events/"),
        ("get", f"{base}/tags/"),
        ("post", f"{base}/tags/"),
        ("patch", f"{base}/tags/{t}/"),
        ("delete", f"{base}/tags/{t}/"),
        ("get", f"{base}/teams/"),
        ("post", f"{base}/teams/"),
        ("patch", f"{base}/teams/{tm}/"),
        ("delete", f"{base}/teams/{tm}/"),
        ("get", f"{base}/assignees/"),
        ("get", f"{base}/attachments/{a}/download/"),
        ("get", f"{base}/widget-settings/"),
        ("patch", f"{base}/widget-settings/"),
    ]


class TestCrossTenantAccess:
    def test_other_org_workspace_endpoints_all_404(self, client_for, tenant_a, tenant_b):
        b = _resources(tenant_b)
        client = client_for(tenant_a.owner)
        for method, url in _urls(tenant_b.workspace.id, b):
            response = getattr(client, method)(url, {}, format="json")
            assert response.status_code == 404, (method, url, response.status_code)
        assert Conversation.objects.filter(workspace=tenant_b.workspace).count() == 1

    def test_foreign_object_ids_under_own_workspace_404(self, client_for, tenant_a, tenant_b):
        """IDOR: valid ids from workspace B addressed through workspace A's URL."""
        b = _resources(tenant_b)
        client = client_for(tenant_a.owner)
        detail_urls = [(m, u) for m, u in _urls(tenant_a.workspace.id, b) if any(str(b[k].id) in u for k in b)]
        assert len(detail_urls) >= 15
        for method, url in detail_urls:
            response = getattr(client, method)(url, {}, format="json")
            assert response.status_code == 404, (method, url, response.status_code)

    def test_cross_workspace_references_rejected(self, client_for, tenant_a, tenant_b):
        a = _resources(tenant_a)
        b = _resources(tenant_b)
        client = client_for(tenant_a.owner)
        base = f"{API}/{tenant_a.workspace.id}"
        cv = a["conversation"].id
        # Foreign tag on own conversation / customer
        r = client.patch(f"{base}/conversations/{cv}/", {"tag_ids": [str(b["tag"].id)]}, format="json")
        assert r.status_code == 400 and r.json()["error"]["code"] == "invalid_tags"
        r = client.patch(f"{base}/customers/{a['customer'].id}/", {"tag_ids": [str(b["tag"].id)]}, format="json")
        assert r.status_code == 400
        # Foreign team / foreign assignee
        r = client.post(f"{base}/conversations/{cv}/assign/", {"team_id": str(b["team"].id)}, format="json")
        assert r.status_code == 400 and r.json()["error"]["code"] == "invalid_team"
        r = client.post(f"{base}/conversations/{cv}/assign/", {"assignee_id": str(tenant_b.owner.id)}, format="json")
        assert r.status_code == 400 and r.json()["error"]["code"] == "invalid_assignee"
        # Start a conversation with a foreign customer
        r = client.post(f"{base}/conversations/", {"customer_id": str(b["customer"].id), "body": "x"}, format="json")
        assert r.status_code == 404
        # Team with a foreign member
        r = client.post(f"{base}/teams/", {"name": "X", "member_ids": [str(tenant_b.owner.id)]}, format="json")
        assert r.status_code == 400

    def test_lists_contain_only_own_workspace(self, client_for, tenant_a, tenant_b):
        _resources(tenant_a)
        _resources(tenant_b)
        client = client_for(tenant_a.owner)
        base = f"{API}/{tenant_a.workspace.id}"
        convs = client.get(f"{base}/conversations/?status=all").json()["results"]
        customers = client.get(f"{base}/customers/").json()["results"]
        assert {c["id"] for c in convs} == {
            str(c.id) for c in Conversation.objects.filter(workspace=tenant_a.workspace)
        }
        assert all(c["id"] for c in customers) and len(customers) == 1
        assert len(client.get(f"{base}/tags/").json()) == 1
        assignees = {u["email"] for u in client.get(f"{base}/assignees/").json()}
        assert tenant_b.owner.email not in assignees


class TestAnonymousAndInactive:
    def test_anonymous_denied(self, api_client, tenant_a):
        r = _resources(tenant_a)
        for method, url in _urls(tenant_a.workspace.id, r):
            response = getattr(api_client, method)(url, {}, format="json")
            assert response.status_code in (401, 403), (method, url, response.status_code)

    def test_widget_token_cannot_call_dashboard_api(self, api_client, tenant_a):
        from apps.customers.services import get_or_create_visitor
        from apps.widget.auth import issue_session_token

        _, identity, _ = get_or_create_visitor(workspace=tenant_a.workspace, raw_token=None)
        token = issue_session_token(identity)
        api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        assert api_client.get(f"{API}/{tenant_a.workspace.id}/conversations/").status_code in (401, 403)
        assert api_client.get("/api/v1/auth/me/").status_code in (401, 403)

    def test_inactive_member_denied(self, client_for, tenant_a):
        r = _resources(tenant_a)
        m = tenant_a.ws_membership(tenant_a.ws_agent)
        m.is_active = False
        m.save()
        client = client_for(tenant_a.ws_agent)
        assert client.get(f"{API}/{tenant_a.workspace.id}/conversations/{r['conversation'].id}/").status_code == 404


@pytest.mark.parametrize(
    ("role_attr", "can_reply", "can_assign", "can_manage_tags", "can_manage_customers"),
    [
        ("owner", True, True, True, True),
        ("ws_agent", True, True, False, True),
        ("ws_viewer", False, False, False, False),
    ],
)
def test_role_matrix(client_for, tenant_a, role_attr, can_reply, can_assign, can_manage_tags, can_manage_customers):
    r = _resources(tenant_a)
    client = client_for(getattr(tenant_a, role_attr))
    base = f"{API}/{tenant_a.workspace.id}"
    cv = r["conversation"].id

    def ok(response) -> bool:  # type: ignore[no-untyped-def]
        assert response.status_code in (200, 201, 204, 403), response.json()
        return response.status_code != 403

    assert client.get(f"{base}/conversations/{cv}/messages/").status_code == 200
    assert ok(client.post(f"{base}/conversations/{cv}/messages/", {"body": "hi"}, format="json")) is can_reply
    assert ok(client.patch(f"{base}/conversations/{cv}/", {"status": "pending"}, format="json")) is can_reply
    assert ok(client.post(f"{base}/conversations/{cv}/assign/", {"assignee_id": None}, format="json")) is can_assign
    assert ok(client.post(f"{base}/tags/", {"name": f"t-{uuid.uuid4().hex[:6]}"}, format="json")) is can_manage_tags
    assert (
        ok(client.patch(f"{base}/customers/{r['customer'].id}/", {"name": "X"}, format="json")) is can_manage_customers
    )
    assert (
        ok(client.post(f"{base}/customers/{r['customer'].id}/notes/", {"body": "n"}, format="json"))
        is can_manage_customers
    )
