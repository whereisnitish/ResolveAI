from __future__ import annotations

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.conversations.models import (
    Conversation,
    ConversationAssignment,
    ConversationEvent,
    Message,
)
from apps.conversations.services import Actor, post_message
from tests.factories import CustomerFactory, TagFactory, TeamFactory, make_conversation

API = "/api/v1/workspaces"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


@pytest.fixture
def base(tenant_a) -> str:
    return f"{API}/{tenant_a.workspace.id}"


class TestLifecycle:
    def test_numbers_are_sequential_per_workspace(self, tenant_a, tenant_b):
        a1, a2 = make_conversation(tenant_a.workspace), make_conversation(tenant_a.workspace)
        b1 = make_conversation(tenant_b.workspace)
        assert (a1.number, a2.number, b1.number) == (1, 2, 1)

    def test_agent_starts_conversation_and_replies(self, client_for, tenant_a, base):
        customer = CustomerFactory(workspace=tenant_a.workspace)
        client = client_for(tenant_a.ws_agent)
        r = client.post(
            f"{base}/conversations/", {"customer_id": str(customer.id), "body": "Following up"}, format="json"
        )
        assert r.status_code == 201, r.json()
        body = r.json()
        assert body["channel"] == "dashboard" and body["status"] == "open"
        assert body["last_message_author_type"] == "agent"
        conv = Conversation.objects.get(id=body["id"])
        assert conv.first_response_at is not None
        assert ConversationEvent.objects.filter(conversation=conv, type="created").exists()

    def test_first_response_time_recorded_once(self, client_for, tenant_a, base):
        conv = make_conversation(tenant_a.workspace)
        assert conv.first_response_at is None
        client = client_for(tenant_a.ws_agent)
        client.post(f"{base}/conversations/{conv.id}/messages/", {"body": "On it"}, format="json")
        conv.refresh_from_db()
        first = conv.first_response_at
        client.post(f"{base}/conversations/{conv.id}/messages/", {"body": "Done"}, format="json")
        conv.refresh_from_db()
        assert first is not None and conv.first_response_at == first

    def test_status_transitions_and_customer_reopen(self, client_for, tenant_a, base):
        conv = make_conversation(tenant_a.workspace)
        client = client_for(tenant_a.ws_agent)
        r = client.patch(f"{base}/conversations/{conv.id}/", {"status": "resolved"}, format="json")
        assert r.json()["status"] == "resolved" and r.json()["resolved_at"]
        post_message(conversation=conv, actor=Actor.of_customer(conv.customer), body="Actually, one more thing")
        conv.refresh_from_db()
        assert conv.status == "open" and conv.resolved_at is None
        types = list(conv.events.values_list("type", flat=True))
        assert types == ["created", "status_changed", "reopened"]

    def test_invalid_status_rejected(self, client_for, tenant_a, base):
        conv = make_conversation(tenant_a.workspace)
        r = client_for(tenant_a.owner).patch(f"{base}/conversations/{conv.id}/", {"status": "deleted"}, format="json")
        assert r.status_code == 400


class TestMessages:
    def test_internal_note_does_not_change_preview_or_reach_widget(self, client_for, tenant_a, base):
        conv = make_conversation(tenant_a.workspace, body="Customer question")
        client = client_for(tenant_a.ws_agent)
        r = client.post(
            f"{base}/conversations/{conv.id}/messages/", {"body": "Secret note", "kind": "note"}, format="json"
        )
        assert r.status_code == 201 and r.json()["kind"] == "note"
        conv.refresh_from_db()
        assert conv.last_message_preview == "Customer question"
        assert conv.first_response_at is None  # a note is not a response

    def test_customer_cannot_write_notes(self, tenant_a):
        from common.exceptions import ServiceError

        conv = make_conversation(tenant_a.workspace)
        with pytest.raises(ServiceError):
            post_message(conversation=conv, actor=Actor.of_customer(conv.customer), body="x", kind="note")

    def test_empty_and_oversized_messages_rejected(self, client_for, tenant_a, base):
        conv = make_conversation(tenant_a.workspace)
        client = client_for(tenant_a.ws_agent)
        assert (
            client.post(f"{base}/conversations/{conv.id}/messages/", {"body": "   "}, format="json").status_code == 400
        )
        too_long = "x" * 10001
        assert (
            client.post(f"{base}/conversations/{conv.id}/messages/", {"body": too_long}, format="json").status_code
            == 400
        )

    def test_message_pagination_newest_first_with_cursor(self, client_for, tenant_a, base):
        conv = make_conversation(tenant_a.workspace)
        for i in range(55):
            post_message(conversation=conv, actor=Actor.agent(tenant_a.ws_agent), body=f"m{i}")
        client = client_for(tenant_a.ws_agent)
        page1 = client.get(f"{base}/conversations/{conv.id}/messages/").json()
        assert len(page1["results"]) == 50 and page1["results"][0]["body"] == "m54"
        page2 = client.get(page1["next"]).json()
        assert len(page2["results"]) == 6 and page2["next"] is None

    def test_attachment_upload_and_download(self, client_for, tenant_a, base):
        conv = make_conversation(tenant_a.workspace)
        client = client_for(tenant_a.ws_agent)
        upload = SimpleUploadedFile("screen shot.png", PNG, content_type="text/html")  # client type is ignored
        r = client.post(f"{base}/conversations/{conv.id}/messages/", {"body": "See attached", "files": [upload]})
        assert r.status_code == 201, r.json()
        att = r.json()["attachments"][0]
        assert att["content_type"] == "image/png" and att["filename"] == "screen shot.png"
        d = client.get(f"{base}/attachments/{att['id']}/download/")
        assert d.status_code == 200
        assert d["Content-Type"] == "image/png"
        assert d["X-Content-Type-Options"] == "nosniff"
        assert "sandbox" in d["Content-Security-Policy"]
        assert b"".join(d.streaming_content) == PNG

    @pytest.mark.parametrize(
        ("name", "content"),
        [
            ("evil.svg", b"<svg onload=alert(1)>"),
            ("page.html", b"<html></html>"),
            ("fake.png", b"<script>alert(1)</script>"),
            ("run.exe", b"MZ\x90\x00"),
            ("empty.txt", b""),
        ],
    )
    def test_dangerous_or_invalid_uploads_rejected(self, client_for, tenant_a, base, name, content):
        conv = make_conversation(tenant_a.workspace)
        r = client_for(tenant_a.ws_agent).post(
            f"{base}/conversations/{conv.id}/messages/", {"body": "x", "files": [SimpleUploadedFile(name, content)]}
        )
        assert r.status_code == 400
        assert "files" in r.json()["error"]["details"]
        assert Message.objects.filter(conversation=conv).count() == 1

    def test_upload_size_limit(self, client_for, tenant_a, base, settings):
        settings.ATTACHMENT_MAX_BYTES = 100
        conv = make_conversation(tenant_a.workspace)
        r = client_for(tenant_a.ws_agent).post(
            f"{base}/conversations/{conv.id}/messages/",
            {"body": "x", "files": [SimpleUploadedFile("big.png", PNG + b"\x00" * 200)]},
        )
        assert r.status_code == 400


class TestAssignment:
    def test_assign_reassign_unassign_with_history(self, client_for, tenant_a, base):
        conv = make_conversation(tenant_a.workspace)
        team = TeamFactory(workspace=tenant_a.workspace)
        client = client_for(tenant_a.owner)
        url = f"{base}/conversations/{conv.id}/assign/"
        r = client.post(url, {"assignee_id": str(tenant_a.ws_agent.id), "team_id": str(team.id)}, format="json")
        assert r.status_code == 200
        assert r.json()["assignee"]["id"] == str(tenant_a.ws_agent.id) and r.json()["team"]["id"] == str(team.id)
        client.post(url, {"assignee_id": str(tenant_a.owner.id)}, format="json")
        r = client.post(url, {"assignee_id": None, "team_id": None}, format="json")
        assert r.json()["assignee"] is None and r.json()["team"] is None
        history = ConversationAssignment.objects.filter(conversation=conv).order_by("created_at")
        assert history.count() == 2 and all(h.ended_at for h in history)
        assert conv.events.filter(type="assigned").count() == 3

    def test_viewer_cannot_be_assigned(self, client_for, tenant_a, base):
        conv = make_conversation(tenant_a.workspace)
        r = client_for(tenant_a.owner).post(
            f"{base}/conversations/{conv.id}/assign/", {"assignee_id": str(tenant_a.ws_viewer.id)}, format="json"
        )
        assert r.status_code == 400 and r.json()["error"]["code"] == "invalid_assignee"

    def test_assignees_list_excludes_viewers_and_billing_admins(self, client_for, tenant_a, base):
        emails = {u["email"] for u in client_for(tenant_a.owner).get(f"{base}/assignees/").json()}
        assert emails == {tenant_a.owner.email, tenant_a.admin.email, tenant_a.ws_agent.email}


class TestInboxQueries:
    def test_filters(self, client_for, tenant_a, base):
        ws = tenant_a.workspace
        tag = TagFactory(workspace=ws)
        mine = make_conversation(ws)
        unassigned = make_conversation(ws)
        resolved = make_conversation(ws)
        client = client_for(tenant_a.ws_agent)
        client.post(
            f"{base}/conversations/{mine.id}/assign/", {"assignee_id": str(tenant_a.ws_agent.id)}, format="json"
        )
        client.patch(
            f"{base}/conversations/{resolved.id}/", {"status": "resolved", "tag_ids": [str(tag.id)]}, format="json"
        )

        def ids(qs: str) -> set[str]:
            return {c["id"] for c in client.get(f"{base}/conversations/?{qs}").json()["results"]}

        assert ids("") == {str(mine.id), str(unassigned.id)}  # default: open
        assert ids("assignee=me") == {str(mine.id)}
        assert ids("assignee=unassigned") == {str(unassigned.id)}
        assert ids("status=resolved") == {str(resolved.id)}
        assert ids("status=all") == {str(mine.id), str(unassigned.id), str(resolved.id)}
        assert ids(f"status=all&tag={tag.id}") == {str(resolved.id)}
        assert ids("assignee=garbage") == set()
        assert ids("status=bogus") == set()

    def test_search_by_message_text_customer_and_number(self, client_for, tenant_a, base):
        ws = tenant_a.workspace
        target = make_conversation(ws, CustomerFactory(workspace=ws, name="Priya Raman"), body="Refund for order 8841")
        other = make_conversation(ws, body="Password help")
        client = client_for(tenant_a.ws_agent)

        def ids(q: str) -> set[str]:
            return {c["id"] for c in client.get(f"{base}/conversations/", {"q": q, "status": "all"}).json()["results"]}

        assert ids("8841") == {str(target.id)}
        assert ids("priya") == {str(target.id)}
        assert ids(f"#{other.number}") == {str(other.id)}

    def test_unread_state_is_per_agent(self, client_for, tenant_a, base):
        conv = make_conversation(tenant_a.workspace)
        agent, owner = client_for(tenant_a.ws_agent), client_for(tenant_a.owner)
        assert agent.get(f"{base}/conversations/{conv.id}/").json()["is_unread"] is True
        assert agent.post(f"{base}/conversations/{conv.id}/read/").status_code == 204
        assert agent.get(f"{base}/conversations/{conv.id}/").json()["is_unread"] is False
        assert owner.get(f"{base}/conversations/{conv.id}/").json()["is_unread"] is True
        assert agent.get(f"{base}/conversations/?unread=true").json()["count"] == 0
        post_message(conversation=conv, actor=Actor.of_customer(conv.customer), body="hello?")
        assert agent.get(f"{base}/conversations/?unread=true").json()["count"] == 1

    def test_counts(self, client_for, tenant_a, base):
        ws = tenant_a.workspace
        team = TeamFactory(workspace=ws)
        c1, c2, c3 = make_conversation(ws), make_conversation(ws), make_conversation(ws)
        client = client_for(tenant_a.ws_agent)
        client.post(
            f"{base}/conversations/{c1.id}/assign/",
            {"assignee_id": str(tenant_a.ws_agent.id), "team_id": str(team.id)},
            format="json",
        )
        client.patch(f"{base}/conversations/{c3.id}/", {"status": "closed"}, format="json")
        counts = client.get(f"{base}/conversations/counts/").json()
        assert counts["mine"] == 1 and counts["unassigned"] == 1 and counts["all"] == 2
        assert counts["by_status"] == {"open": 2, "pending": 0, "resolved": 0, "closed": 1}
        assert counts["by_team"] == {str(team.id): 1}
        assert c2

    def test_tags_events_record_names(self, client_for, tenant_a, base):
        conv = make_conversation(tenant_a.workspace)
        t1, t2 = (
            TagFactory(workspace=tenant_a.workspace, name="billing"),
            TagFactory(workspace=tenant_a.workspace, name="vip"),
        )
        client = client_for(tenant_a.ws_agent)
        client.patch(f"{base}/conversations/{conv.id}/", {"tag_ids": [str(t1.id), str(t2.id)]}, format="json")
        client.patch(f"{base}/conversations/{conv.id}/", {"tag_ids": [str(t2.id)]}, format="json")
        events = client.get(f"{base}/conversations/{conv.id}/events/").json()
        tag_events = [e["data"] for e in events if e["type"] == "tags_changed"]
        assert tag_events == [{"added": ["billing", "vip"], "removed": []}, {"added": [], "removed": ["billing"]}]

    def test_list_query_count_is_bounded(self, client_for, tenant_a, base, django_assert_max_num_queries):
        for _ in range(10):
            conv = make_conversation(tenant_a.workspace)
            conv.tags.add(TagFactory(workspace=tenant_a.workspace))
        client = client_for(tenant_a.ws_agent)
        with django_assert_max_num_queries(14):
            r = client.get(f"{base}/conversations/")
        assert r.json()["count"] == 10


class TestCatalog:
    def test_tag_names_unique_case_insensitive(self, client_for, tenant_a, base):
        client = client_for(tenant_a.owner)
        assert client.post(f"{base}/tags/", {"name": "VIP"}, format="json").status_code == 201
        r = client.post(f"{base}/tags/", {"name": "vip"}, format="json")
        assert r.status_code == 409 and r.json()["error"]["code"] == "duplicate_name"
        assert client.post(f"{base}/tags/", {"name": "x", "color": "red"}, format="json").status_code == 400

    def test_team_crud(self, client_for, tenant_a, base):
        client = client_for(tenant_a.owner)
        r = client.post(f"{base}/teams/", {"name": "Billing", "member_ids": [str(tenant_a.ws_agent.id)]}, format="json")
        assert r.status_code == 201 and [m["email"] for m in r.json()["members"]] == [tenant_a.ws_agent.email]
        r = client.patch(f"{base}/teams/{r.json()['id']}/", {"member_ids": []}, format="json")
        assert r.json()["members"] == []
