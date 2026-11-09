from __future__ import annotations

import hashlib
import hmac
import json
from datetime import timedelta

import pytest
from django.utils import timezone
from freezegun import freeze_time

from apps.conversations.models import Conversation
from apps.conversations.services import Actor, post_message, start_conversation, update_conversation
from apps.integrations import services as integration_services
from apps.integrations.models import Integration, IntegrationDelivery
from apps.workflows.engine import scan_unanswered
from apps.workflows.models import Workflow, WorkflowExecution
from common import crypto
from common.safe_http import SafeResponse
from tests.factories import (
    CustomerFactory,
    OrganizationMembershipFactory,
    TagFactory,
    TeamFactory,
    UserFactory,
    WorkspaceMembershipFactory,
)

# ---------------------------------------------------------------------------
# Workflows
# ---------------------------------------------------------------------------


@pytest.fixture
def start(tenant_a, django_capture_on_commit_callbacks):  # type: ignore[no-untyped-def]
    def _start(body: str = "Hello") -> Conversation:
        customer = CustomerFactory(workspace=tenant_a.workspace)
        with django_capture_on_commit_callbacks(execute=True):
            conv, _ = start_conversation(
                workspace=tenant_a.workspace, customer=customer, actor=Actor.of_customer(customer), body=body
            )
        conv.refresh_from_db()
        return conv

    return _start


def _wf(tenant, **kwargs) -> Workflow:  # type: ignore[no-untyped-def]
    return Workflow.objects.create(workspace=tenant.workspace, name=kwargs.pop("name", "wf"), **kwargs)


class TestWorkflowValidation:
    def test_api_validates_definition_and_scopes_references(self, client_for, tenant_a, tenant_b):
        url = f"/api/v1/workspaces/{tenant_a.workspace.id}/workflows/"
        client = client_for(tenant_a.owner)
        bad_cases = [
            {"actions": [{"type": "run_python", "code": "import os"}]},
            {"actions": [{"type": "add_tag", "tag_id": str(TagFactory(workspace=tenant_b.workspace).id)}]},
            {"actions": [{"type": "assign_user", "user_id": str(tenant_b.owner.id)}]},
            {"actions": [{"type": "set_priority", "priority": "mega"}]},
            {"actions": []},
            {
                "conditions": {"rules": [{"field": "customer.password", "operator": "eq", "value": "x"}]},
                "actions": [{"type": "add_note", "body": "x"}],
            },
        ]
        for case in bad_cases:
            payload = {"name": "x", "trigger": "conversation_created", **case}
            assert client.post(url, payload, format="json").status_code == 400, case
        r = client.post(
            url,
            {
                "name": "x",
                "trigger": "conversation_unanswered",
                "trigger_config": {"minutes": 0},
                "actions": [{"type": "add_note", "body": "x"}],
            },
            format="json",
        )
        assert r.status_code == 400
        ok = client.post(
            url,
            {"name": "Welcome", "trigger": "conversation_created", "actions": [{"type": "send_reply", "body": "Hi!"}]},
            format="json",
        )
        assert ok.status_code == 201
        assert client_for(tenant_a.ws_agent).post(url, {"name": "x"}, format="json").status_code == 403
        assert client_for(tenant_b.owner).get(url).status_code == 404
        assert client.get(f"{url}schema/").json()["actions"]


class TestWorkflowExecution:
    def test_welcome_and_tag_on_new_conversation_runs_once(self, tenant_a, start):
        tag = TagFactory(workspace=tenant_a.workspace, name="new")
        _wf(
            tenant_a,
            trigger="conversation_created",
            actions=[
                {"type": "send_reply", "body": "Thanks for reaching out!"},
                {"type": "add_tag", "tag_id": str(tag.id)},
            ],
        )
        conv = start()
        assert conv.messages.filter(author_type="system", body="Thanks for reaching out!").count() == 1
        assert list(conv.tags.values_list("name", flat=True)) == ["new"]
        from apps.workflows.engine import dispatch

        dispatch("conversation_created", str(conv.id), None, "created")  # retry/duplicate
        assert WorkflowExecution.objects.count() == 1

    def test_intent_tagging_on_customer_message(self, tenant_a, start):
        tag = TagFactory(workspace=tenant_a.workspace, name="refund")
        _wf(
            tenant_a,
            trigger="customer_message",
            conditions={
                "match": "any",
                "rules": [{"field": "message.text", "operator": "contains", "value": "refund, money back"}],
            },
            actions=[{"type": "add_tag", "tag_id": str(tag.id)}, {"type": "set_priority", "priority": "high"}],
        )
        assert start("Where is my order?").tags.count() == 0
        conv = start("I want my money back")
        assert conv.priority == "high" and conv.tags.filter(name="refund").exists()

    def test_round_robin_picks_least_loaded_member(self, tenant_a, start):
        team = TeamFactory(workspace=tenant_a.workspace)
        busy, free = tenant_a.ws_agent, UserFactory()
        OrganizationMembershipFactory(organization=tenant_a.org, user=free)
        WorkspaceMembershipFactory(workspace=tenant_a.workspace, user=free, role="agent")
        team.members.set([busy, free])
        Conversation.objects.filter(workspace=tenant_a.workspace).delete()
        existing = start("first")
        existing.assignee = busy
        existing.save()
        _wf(tenant_a, trigger="conversation_created", actions=[{"type": "assign_round_robin", "team_id": str(team.id)}])
        conv = start("needs help")
        assert conv.assignee == free and conv.team == team

    def test_workflow_actions_do_not_trigger_workflows(self, tenant_a, start, django_capture_on_commit_callbacks):
        _wf(tenant_a, trigger="customer_message", actions=[{"type": "set_status", "status": "resolved"}])
        _wf(
            tenant_a,
            name="on-resolve",
            trigger="conversation_resolved",
            actions=[{"type": "add_note", "body": "resolved!"}],
        )
        conv = start("thanks, all good")
        assert conv.status == "resolved"
        assert not conv.messages.filter(kind="note").exists()  # resolve came from a workflow
        with django_capture_on_commit_callbacks(execute=True):
            update_conversation(conversation=conv, data={"status": "open"}, actor=Actor.agent(tenant_a.owner))
            update_conversation(conversation=conv, data={"status": "resolved"}, actor=Actor.agent(tenant_a.owner))
        assert conv.messages.filter(kind="note", body="resolved!").count() == 1

    def test_unanswered_escalation(self, tenant_a, start):
        team = TeamFactory(workspace=tenant_a.workspace, name="Tier 2")
        _wf(
            tenant_a,
            trigger="conversation_unanswered",
            trigger_config={"minutes": 15},
            actions=[{"type": "assign_team", "team_id": str(team.id)}, {"type": "set_priority", "priority": "urgent"}],
        )
        conv = start("hello?")
        answered = start("other")
        post_message(conversation=answered, actor=Actor.agent(tenant_a.ws_agent), body="Hi!")
        with freeze_time(timezone.now() + timedelta(minutes=10)):
            assert scan_unanswered() == 0
        with freeze_time(timezone.now() + timedelta(minutes=20)):
            assert scan_unanswered() == 1
            assert scan_unanswered() == 0  # idempotent per waiting period
        conv.refresh_from_db()
        assert conv.team == team and conv.priority == "urgent"


# ---------------------------------------------------------------------------
# Integrations
# ---------------------------------------------------------------------------
class TestIntegrations:
    @pytest.fixture(autouse=True)
    def _public_dns(self, monkeypatch):  # type: ignore[no-untyped-def]
        monkeypatch.setattr("common.safe_http._is_public", lambda ip: not ip.startswith(("127.", "10.", "169.254.")))
        monkeypatch.setattr("socket.getaddrinfo", lambda host, port: [(0, 0, 0, "", ("93.184.216.34", port))])

    def test_create_returns_secret_once_and_encrypts_url(self, client_for, tenant_a):
        url = f"/api/v1/workspaces/{tenant_a.workspace.id}/integrations/"
        client = client_for(tenant_a.owner)
        r = client.post(
            url,
            {
                "kind": "webhook",
                "name": "CRM",
                "url": "https://crm.example.com/hook?token=abc",
                "events": ["conversation.created"],
            },
            format="json",
        )
        assert r.status_code == 201 and r.json()["signing_secret"].startswith("whsec_")
        integration = Integration.objects.get()
        assert "crm.example.com" not in integration.url_encrypted
        assert crypto.decrypt(integration.url_encrypted).endswith("token=abc")
        listed = client.get(url).json()[0]
        assert "signing_secret" not in listed and "token=abc" not in json.dumps(listed)
        assert listed["url_host"] == "crm.example.com"
        assert client_for(tenant_a.ws_agent).get(url).status_code == 403

    def test_rejects_unsafe_and_wrong_slack_urls(self, client_for, tenant_a, monkeypatch):
        url = f"/api/v1/workspaces/{tenant_a.workspace.id}/integrations/"
        client = client_for(tenant_a.owner)
        monkeypatch.setattr("socket.getaddrinfo", lambda host, port: [(0, 0, 0, "", ("10.0.0.7", port))])
        r = client.post(
            url,
            {"kind": "webhook", "name": "x", "url": "https://internal.corp/hook", "events": ["conversation.created"]},
            format="json",
        )
        assert r.status_code == 400
        monkeypatch.setattr("socket.getaddrinfo", lambda host, port: [(0, 0, 0, "", ("93.184.216.34", port))])
        r = client.post(
            url,
            {
                "kind": "slack",
                "name": "x",
                "url": "https://evil.example.com/services/x",
                "events": ["conversation.created"],
            },
            format="json",
        )
        assert r.status_code == 400

    def test_events_are_delivered_signed(self, tenant_a, start, monkeypatch):
        sent = []
        monkeypatch.setattr(
            integration_services,
            "safe_request",
            lambda method, url, **kw: sent.append((url, kw)) or SafeResponse(url, 200, "application/json", b"ok"),
        )
        _integration, secret = integration_services.create_integration(
            workspace=tenant_a.workspace,
            kind="webhook",
            name="CRM",
            url="https://crm.example.com/h",
            events=["conversation.created"],
            user=tenant_a.owner,
        )
        start("New lead here")
        assert len(sent) == 1
        _url, kw = sent[0]
        header = kw["headers"]["X-ResolveAI-Signature"]
        ts, sig = header.split(",")[0][2:], header.split(",")[1][3:]
        expected = hmac.new(secret.encode(), f"{ts}.".encode() + kw["content"], hashlib.sha256).hexdigest()
        assert hmac.compare_digest(sig, expected)
        payload = json.loads(kw["content"])
        assert payload["type"] == "conversation.created" and payload["workspace_id"] == str(tenant_a.workspace.id)
        assert IntegrationDelivery.objects.get().status == "succeeded"

    def test_failed_delivery_retries_then_fails(self, tenant_a, start, monkeypatch):
        from apps.integrations import tasks

        # Celery schedules retries with backoff; here we drive each attempt directly.
        monkeypatch.setattr(tasks.deliver_task, "delay", lambda *a, **k: None)
        monkeypatch.setattr(integration_services, "safe_request", lambda *a, **k: SafeResponse("u", 503, "", b""))
        integration_services.create_integration(
            workspace=tenant_a.workspace,
            kind="webhook",
            name="Down",
            url="https://down.example.com/h",
            events=["conversation.created"],
            user=tenant_a.owner,
        )
        start("hi")
        delivery = IntegrationDelivery.objects.get()
        for _ in range(integration_services.MAX_ATTEMPTS - 1):
            with pytest.raises(integration_services.RetryableDeliveryError):
                integration_services.deliver(str(delivery.id))
        integration_services.deliver(str(delivery.id))  # final attempt: no more retries
        delivery.refresh_from_db()
        assert delivery.status == "failed" and delivery.attempts == integration_services.MAX_ATTEMPTS
        assert delivery.response_status == 503 and Integration.objects.get().consecutive_failures == 5

    def test_other_workspace_events_not_sent(self, tenant_a, tenant_b, start, monkeypatch):
        monkeypatch.setattr(integration_services, "safe_request", lambda *a, **k: SafeResponse("u", 200, "", b""))
        integration_services.create_integration(
            workspace=tenant_b.workspace,
            kind="webhook",
            name="B",
            url="https://b.example.com/h",
            events=["conversation.created"],
            user=tenant_b.owner,
        )
        start("hi from A")
        assert not IntegrationDelivery.objects.exists()


# ---------------------------------------------------------------------------
# Analytics
# ---------------------------------------------------------------------------
class TestAnalytics:
    def test_metrics(self, client_for, tenant_a, tenant_b, start, django_capture_on_commit_callbacks):
        from apps.ai_agents.models import AIAgent
        from apps.knowledge.models import KnowledgeSource
        from apps.knowledge.services import ingest_source

        source = KnowledgeSource.objects.create(
            workspace=tenant_a.workspace,
            kind="faq",
            title="FAQ",
            faq=[{"question": "Do you ship to Pune?", "answer": "Yes, within 3 days."}],
        )
        ingest_source(source.id)
        AIAgent.objects.create(
            workspace=tenant_a.workspace, name="Ava", provider="mock", model="mock-1", is_deployed=True
        )

        ai_conv = start("Do you ship to Pune?")
        handoff_conv = start("I need a human")
        human_conv = start("random question about warranty claims")
        with django_capture_on_commit_callbacks(execute=True):
            post_message(conversation=human_conv, actor=Actor.agent(tenant_a.ws_agent), body="Let me check.")
            for c in (ai_conv, human_conv):
                update_conversation(conversation=c, data={"status": "resolved"}, actor=Actor.agent(tenant_a.ws_agent))
        CustomerFactory(workspace=tenant_b.workspace)  # other tenant noise

        r = client_for(tenant_a.ws_viewer).get(f"/api/v1/workspaces/{tenant_a.workspace.id}/analytics/")
        assert r.status_code == 200
        d = r.json()
        assert d["conversations"]["total"] == 3 and d["conversations"]["resolved"] == 2
        assert d["ai"]["resolved_without_human"] == 1 and d["ai"]["resolution_rate"] == 0.5
        assert d["ai"]["involved_conversations"] == 3 and d["ai"]["handoff_rate"] == pytest.approx(2 / 3, abs=0.01)
        assert d["response_times"]["avg_first_response_seconds"] is not None
        assert [a["name"] for a in d["agents"]] == [tenant_a.ws_agent.full_name]
        assert d["agents"][0]["resolved"] == 2
        assert sum(day["created"] for day in d["daily"]) == 3 and len(d["daily"]) == 30
        assert handoff_conv.ai_state == "handed_off"

    def test_isolation_and_permissions(self, client_for, tenant_a, tenant_b, start):
        start("only in A")
        url_b = f"/api/v1/workspaces/{tenant_b.workspace.id}/analytics/"
        assert client_for(tenant_b.owner).get(url_b).json()["conversations"]["total"] == 0
        assert client_for(tenant_a.owner).get(url_b).status_code == 404
        org_url = f"/api/v1/organizations/{tenant_a.org.id}/analytics/"
        assert client_for(tenant_a.owner).get(org_url).json()["conversations"]["total"] == 1
        assert client_for(tenant_a.member).get(org_url).status_code == 403
        assert client_for(tenant_a.owner).get(f"{org_url}?start=2026-13-01").status_code == 400
        assert client_for(tenant_a.owner).get(f"{org_url}?start=2020-01-01&end=2026-01-01").status_code == 400
