from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest

from apps.ai_agents import providers
from apps.ai_agents.models import AIAgent, AIExecution, ToolExecution
from apps.ai_agents.providers import LLMRequest, LLMResponse, MockProvider, ProviderError
from apps.billing.models import UsageLedger
from apps.conversations.models import Conversation, Message
from apps.conversations.services import Actor, post_message, start_conversation
from apps.knowledge.models import KnowledgeSource
from apps.knowledge.services import ingest_source
from tests.factories import CustomerFactory, TeamFactory
from tests.helpers import set_plan

FAQ = [
    {"question": "Do you ship to Pune?", "answer": "Yes, we ship across India including Pune within 3 business days."},
    {"question": "What is your refund policy?", "answer": "Refunds are processed within 5 days of receiving the item."},
]


@pytest.fixture
def agent(tenant_a) -> AIAgent:
    source = KnowledgeSource.objects.create(workspace=tenant_a.workspace, kind="faq", title="FAQ", faq=FAQ)
    ingest_source(source.id)
    return AIAgent.objects.create(
        workspace=tenant_a.workspace,
        name="Ava",
        instructions="You are Ava. Secret escalation codeword is pineapple sunrise protocol seven always.",
        provider="mock",
        model="mock-1",
        is_deployed=True,
    )


@pytest.fixture
def ask(tenant_a, django_capture_on_commit_callbacks):  # type: ignore[no-untyped-def]
    """Customer writes in (as through the widget); returns the conversation after the AI ran."""

    def _ask(text: str, conversation: Conversation | None = None) -> Conversation:
        with django_capture_on_commit_callbacks(execute=True):
            if conversation is None:
                customer = CustomerFactory(workspace=tenant_a.workspace)
                conversation, _ = start_conversation(
                    workspace=tenant_a.workspace, customer=customer, actor=Actor.of_customer(customer), body=text
                )
            else:
                post_message(conversation=conversation, actor=Actor.of_customer(conversation.customer), body=text)
        conversation.refresh_from_db()
        return conversation

    return _ask


def _ai_messages(conv: Conversation) -> list[str]:
    return list(conv.messages.filter(author_type="ai").order_by("created_at").values_list("body", flat=True))


class TestConversationReplies:
    def test_answers_from_knowledge_and_meters_usage(self, agent, ask, tenant_a):
        conv = ask("Hi, do you ship to Pune?")
        assert _ai_messages(conv) == ["Yes, we ship across India including Pune within 3 business days."]
        execution = AIExecution.objects.get(conversation=conv)
        assert execution.status == "answered" and execution.confidence == pytest.approx(0.82)
        assert execution.retrieved and execution.retrieved[0]["title"] == "FAQ"
        assert [s["node"] for s in execution.steps] == ["check_request", "retrieve", "generate", "validate", "decide"]
        assert execution.response_message.author_type == "ai"
        metrics = dict(
            UsageLedger.objects.filter(organization=tenant_a.org)
            .values_list("metric", "quantity")
            .filter(source_type="ai_execution")
        )
        assert metrics["ai_executions"] == 1 and metrics["ai_conversations"] == 1 and metrics["ai_input_tokens"] > 0
        assert conv.ai_state == "active"

    def test_no_knowledge_hands_off_without_llm_call(self, agent, ask, tenant_a):
        team = TeamFactory(workspace=tenant_a.workspace)
        agent.handoff_team = team
        agent.save()
        conv = ask("Can you fix my quantum flux capacitor?")
        assert _ai_messages(conv) == [agent.handoff_message]
        assert conv.ai_state == "handed_off" and conv.team_id == team.id
        execution = AIExecution.objects.get(conversation=conv)
        assert execution.status == "handed_off" and execution.handoff_reason == "no relevant knowledge"
        assert not UsageLedger.objects.filter(metric="ai_executions").exists()  # no model call, no charge
        assert conv.events.filter(type="handoff").exists()

    def test_customer_requests_human(self, agent, ask):
        conv = ask("I want to talk to a real person please")
        assert conv.ai_state == "handed_off"
        assert AIExecution.objects.get(conversation=conv).handoff_reason == "customer asked for a human"

    def test_after_handoff_ai_stays_silent(self, agent, ask):
        conv = ask("talk to a human")
        conv = ask("Do you ship to Pune?", conv)
        assert len(_ai_messages(conv)) == 1
        assert AIExecution.objects.filter(conversation=conv).latest("created_at").skip_reason == "ai_handed_off"

    def test_internal_notes_never_reach_the_model(self, agent, ask, tenant_a, monkeypatch):
        seen: list[LLMRequest] = []
        original = MockProvider.complete
        monkeypatch.setattr(MockProvider, "complete", lambda self, req: seen.append(req) or original(self, req))
        conv = ask("Do you ship to Pune?")
        post_message(
            conversation=conv, actor=Actor.agent(tenant_a.ws_agent), body="VIP: secret internal remark", kind="note"
        )
        conv.ai_state = "active"
        conv.save()
        ask("And what about refunds?", conv)
        assert all("secret internal remark" not in m.content for req in seen for m in req.messages)
        assert "secret internal remark" not in seen[-1].system

    def test_no_deployed_agent_means_no_ai(self, agent, ask):
        agent.is_deployed = False
        agent.save()
        conv = ask("Do you ship to Pune?")
        assert _ai_messages(conv) == [] and not AIExecution.objects.exists()


class TestHumanTakeover:
    """Critical security test #7: the AI must not reply after a human took control."""

    def test_agent_reply_pauses_ai(self, agent, ask, tenant_a):
        conv = ask("Do you ship to Pune?")
        post_message(conversation=conv, actor=Actor.agent(tenant_a.ws_agent), body="Hi, Asha here!")
        conv.refresh_from_db()
        assert conv.ai_state == "paused" and conv.human_takeover_at
        conv = ask("What is your refund policy?", conv)
        assert len(_ai_messages(conv)) == 1
        assert AIExecution.objects.filter(conversation=conv).latest("created_at").skip_reason == "ai_paused"

    def test_takeover_during_generation_blocks_delivery(self, agent, ask, tenant_a, monkeypatch):
        original = MockProvider.complete

        def slow_model(self, request):  # type: ignore[no-untyped-def]
            conv = Conversation.objects.get(workspace=tenant_a.workspace)
            post_message(conversation=conv, actor=Actor.agent(tenant_a.ws_agent), body="I've got this one.")
            return original(self, request)

        monkeypatch.setattr(MockProvider, "complete", slow_model)
        conv = ask("Do you ship to Pune?")
        assert _ai_messages(conv) == []
        execution = AIExecution.objects.get(conversation=conv, status="skipped")
        assert execution.skip_reason == "human_took_over_during_generation"

    def test_allowed_when_workspace_configured(self, agent, ask, tenant_a):
        agent.allow_after_human_takeover = True
        agent.save()
        conv = ask("Do you ship to Pune?")
        post_message(conversation=conv, actor=Actor.agent(tenant_a.ws_agent), body="Hi!")
        conv = ask("What is your refund policy?", conv)
        assert len(_ai_messages(conv)) == 2

    def test_take_over_and_resume_endpoints(self, agent, ask, tenant_a, client_for):
        conv = ask("Do you ship to Pune?")
        base = f"/api/v1/workspaces/{tenant_a.workspace.id}/conversations/{conv.id}/ai"
        client = client_for(tenant_a.ws_agent)
        assert client.post(f"{base}/take-over/").json()["ai_state"] == "paused"
        assert client.post(f"{base}/resume/").json()["ai_state"] == "active"
        conv = ask("What is your refund policy?", conv)
        assert len(_ai_messages(conv)) == 2
        assert client_for(tenant_a.ws_viewer).post(f"{base}/take-over/").status_code == 403


class TestSafetyAndDecisions:
    def _script(self, monkeypatch, *payloads: dict[str, Any], refused: bool = False) -> None:  # type: ignore[no-untyped-def]
        queue = list(payloads)

        def fake(self, request):  # type: ignore[no-untyped-def]
            data = {
                "answer": "",
                "confidence": 0.9,
                "needs_human": False,
                "reason": "",
                "tool_name": "",
                "tool_arguments_json": "{}",
            }
            data.update(queue.pop(0))
            return LLMResponse(
                json.dumps(data), None if refused else data, 10, 5, "mock-1", "end_turn", refused=refused
            )

        monkeypatch.setattr(MockProvider, "complete", fake)

    def test_instruction_leak_is_blocked(self, agent, ask, monkeypatch):
        self._script(
            monkeypatch, {"answer": "Sure! Secret escalation codeword is pineapple sunrise protocol seven always."}
        )
        conv = ask("Do you ship to Pune?")
        assert "pineapple" not in " ".join(_ai_messages(conv))
        assert AIExecution.objects.get(conversation=conv).handoff_reason == "answer blocked: possible instruction leak"

    def test_low_confidence_hands_off(self, agent, ask, monkeypatch):
        self._script(monkeypatch, {"answer": "Maybe?", "confidence": 0.3})
        conv = ask("Do you ship to Pune?")
        assert conv.ai_state == "handed_off"
        assert AIExecution.objects.get(conversation=conv).handoff_reason.startswith("low confidence")

    def test_refusal_hands_off(self, agent, ask, monkeypatch):
        self._script(monkeypatch, {"answer": "x"}, refused=True)
        conv = ask("Do you ship to Pune?")
        assert AIExecution.objects.get(conversation=conv).handoff_reason == "model declined to answer"

    def test_provider_error_hands_off_and_is_logged(self, agent, ask, monkeypatch):
        def boom(self, request):  # type: ignore[no-untyped-def]
            raise ProviderError("Anthropic rate limit reached.", retryable=True)

        monkeypatch.setattr(MockProvider, "complete", boom)
        conv = ask("Do you ship to Pune?")
        execution = AIExecution.objects.get(conversation=conv)
        assert execution.status == "handed_off" and "rate limit" in execution.error
        assert conv.ai_state == "handed_off"

    def test_tool_call_loop_is_logged(self, agent, ask, monkeypatch):
        self._script(
            monkeypatch,
            {"tool_name": "search_knowledge", "tool_arguments_json": json.dumps({"query": "refund"})},
            {"tool_name": "delete_database", "tool_arguments_json": "{}"},
            {"answer": "Refunds take 5 days."},
        )
        conv = ask("Do you ship to Pune?")
        assert _ai_messages(conv) == ["Refunds take 5 days."]
        tools = list(ToolExecution.objects.order_by("created_at").values_list("tool_name", "status"))
        assert tools == [("search_knowledge", "succeeded"), ("delete_database", "failed")]

    def test_quota_exhausted_hands_off_without_model_call(self, agent, ask, tenant_a, monkeypatch):
        set_plan(tenant_a.org, "starter", ai_executions_per_month=0)
        called = []
        monkeypatch.setattr(MockProvider, "complete", lambda self, r: called.append(r))
        conv = ask("Do you ship to Pune?")
        assert called == [] and conv.ai_state == "handed_off"
        assert AIExecution.objects.get(conversation=conv).status == "quota_exceeded"


class TestPlaygroundAndStudio:
    def test_playground_dry_run(self, agent, client_for, tenant_a):
        url = f"/api/v1/workspaces/{tenant_a.workspace.id}/ai-agents/{agent.id}/playground/"
        r = client_for(tenant_a.owner).post(
            url, {"messages": [{"role": "user", "content": "refund policy?"}]}, format="json"
        )
        assert r.status_code == 200, r.json()
        body = r.json()
        assert body["decision"] == "answer" and "Refunds" in body["answer"]
        assert body["sources"][0]["title"] == "FAQ" and body["input_tokens"] > 0
        assert not Message.objects.exists()
        assert AIExecution.objects.get(id=body["execution_id"]).source == "playground"
        assert (
            client_for(tenant_a.ws_agent)
            .post(url, {"messages": [{"role": "user", "content": "x"}]}, format="json")
            .status_code
            == 403
        )
        bad = client_for(tenant_a.owner).post(url, {"messages": [{"role": "assistant", "content": "x"}]}, format="json")
        assert bad.status_code == 400

    def test_one_deployed_agent_per_workspace(self, agent, client_for, tenant_a):
        base = f"/api/v1/workspaces/{tenant_a.workspace.id}/ai-agents/"
        client = client_for(tenant_a.owner)
        second = client.post(base, {"name": "Bob", "provider": "openai"}, format="json").json()
        assert second["model"] == "gpt-5.5"  # provider default applied
        client.post(f"{base}{second['id']}/deploy/")
        agent.refresh_from_db()
        assert not agent.is_deployed
        assert [a["name"] for a in client.get(base).json() if a["is_deployed"]] == ["Bob"]

    def test_agent_config_rejects_foreign_knowledge_and_team(self, agent, client_for, tenant_a, tenant_b):
        foreign = KnowledgeSource.objects.create(workspace=tenant_b.workspace, kind="text", title="B", text="b")
        url = f"/api/v1/workspaces/{tenant_a.workspace.id}/ai-agents/{agent.id}/"
        client = client_for(tenant_a.owner)
        assert client.patch(url, {"knowledge_source_ids": [str(foreign.id)]}, format="json").status_code == 400
        assert (
            client.patch(
                url, {"handoff_team_id": str(TeamFactory(workspace=tenant_b.workspace).id)}, format="json"
            ).status_code
            == 400
        )

    def test_isolation(self, agent, client_for, tenant_b, tenant_a):
        b = client_for(tenant_b.owner)
        assert b.get(f"/api/v1/workspaces/{tenant_a.workspace.id}/ai-agents/").status_code == 404
        b_url = f"/api/v1/workspaces/{tenant_b.workspace.id}/ai-agents/{agent.id}/"
        assert b.get(b_url).status_code == 404
        assert (
            b.post(f"{b_url}playground/", {"messages": [{"role": "user", "content": "x"}]}, format="json").status_code
            == 404
        )

    def test_summarize(self, agent, ask, client_for, tenant_a):
        conv = ask("Do you ship to Pune?")
        r = client_for(tenant_a.ws_agent).post(
            f"/api/v1/workspaces/{tenant_a.workspace.id}/conversations/{conv.id}/ai/summarize/"
        )
        assert r.status_code == 200 and "Customer asked" in r.json()["ai_summary"]

    def test_widget_shows_ai_author(self, agent, ask):
        from apps.widget.serializers import widget_message_payload

        conv = ask("Do you ship to Pune?")
        assert widget_message_payload(conv.messages.get(author_type="ai"))["author_name"] == "AI assistant"


class TestProviders:
    def test_mock_fallback_and_not_configured(self, settings):
        assert isinstance(providers.get_provider("anthropic"), MockProvider)
        settings.AI_ALLOW_MOCK_FALLBACK = False
        with pytest.raises(providers.ProviderNotConfigured):
            providers.get_provider("openai")

    def test_anthropic_request_shape_and_parsing(self, settings, monkeypatch):
        import anthropic

        captured: dict[str, Any] = {}

        class FakeMessages:
            def create(self, **kwargs: Any) -> Any:
                captured.update(kwargs)
                return SimpleNamespace(
                    content=[
                        SimpleNamespace(type="thinking", thinking=""),
                        SimpleNamespace(type="text", text='{"answer": "hi"}'),
                    ],
                    stop_reason="end_turn",
                    usage=SimpleNamespace(input_tokens=120, output_tokens=30),
                    model="claude-opus-5-5",
                )

        class FakeClient:
            def __init__(self, **kwargs: Any) -> None:
                captured["client_kwargs"] = kwargs
                self.beta = SimpleNamespace(messages=FakeMessages())

        monkeypatch.setattr(anthropic, "Anthropic", FakeClient)
        settings.ANTHROPIC_API_KEY = "sk-ant-test"
        provider = providers.get_provider("anthropic")
        response = provider.complete(
            LLMRequest(
                system="sys",
                messages=[providers.ChatTurn("user", "q")],
                model="claude-opus-5-5",
                json_schema={"type": "object"},
            )
        )
        assert captured["output_config"] == {
            "effort": "medium",
            "format": {"type": "json_schema", "schema": {"type": "object"}},
        }
        assert captured["fallbacks"] == "default" and captured["betas"] == ["server-side-fallback-2026-07-01"]
        assert "temperature" not in captured
        assert captured["client_kwargs"]["max_retries"] == 2
        assert response.data == {"answer": "hi"} and response.input_tokens == 120 and not response.refused

    def test_anthropic_refusal(self, settings, monkeypatch):
        import anthropic

        class FakeClient:
            def __init__(self, **kwargs: Any) -> None:
                self.beta = SimpleNamespace(
                    messages=SimpleNamespace(
                        create=lambda **k: SimpleNamespace(
                            content=[],
                            stop_reason="refusal",
                            usage=SimpleNamespace(input_tokens=5, output_tokens=0),
                            model="m",
                        )
                    )
                )

        monkeypatch.setattr(anthropic, "Anthropic", FakeClient)
        settings.ANTHROPIC_API_KEY = "sk-ant-test"
        response = providers.get_provider("anthropic").complete(
            LLMRequest(system="s", messages=[providers.ChatTurn("user", "q")], model="claude-haiku-5-5", json_schema={})
        )
        assert response.refused and response.data is None

    def test_openai_request_shape(self, settings, monkeypatch):
        import openai

        captured: dict[str, Any] = {}

        def create(**kwargs: Any) -> Any:
            captured.update(kwargs)
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(content='{"answer": "ok"}', refusal=None), finish_reason="stop"
                    )
                ],
                usage=SimpleNamespace(prompt_tokens=50, completion_tokens=7),
                model="gpt-5.5",
            )

        class FakeClient:
            def __init__(self, **kwargs: Any) -> None:
                self.chat = SimpleNamespace(completions=SimpleNamespace(create=create))

        monkeypatch.setattr(openai, "OpenAI", FakeClient)
        settings.OPENAI_API_KEY = "sk-test"
        response = providers.get_provider("openai").complete(
            LLMRequest(
                system="sys",
                messages=[providers.ChatTurn("user", "q")],
                model="gpt-5.5",
                json_schema={"type": "object"},
            )
        )
        assert captured["messages"][0] == {"role": "system", "content": "sys"}
        assert captured["response_format"]["json_schema"]["strict"] is True
        assert captured["reasoning_effort"] == "medium"
        assert response.data == {"answer": "ok"} and response.output_tokens == 7
