"""AI Agent Studio API: /api/v1/workspaces/{ws}/ai-agents/... and conversation AI actions."""

from __future__ import annotations

from typing import Any

from django.db.models import QuerySet
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from apps.ai_agents import services
from apps.ai_agents.models import DEFAULT_MODELS, AIAgent, AIExecution, Effort, Provider, ToolExecution
from apps.ai_agents.providers import provider_status
from apps.conversations.models import AIState, Conversation
from apps.conversations.services import Actor, set_ai_state
from apps.conversations.views import ConversationViewSet
from apps.knowledge.models import KnowledgeSource
from apps.tenancy.views import WorkspaceScopedViewMixin
from apps.workspaces.models import Team
from common.rbac import Perm


class AIAgentSerializer(serializers.ModelSerializer):
    knowledge_source_ids = serializers.PrimaryKeyRelatedField(
        source="knowledge_sources", many=True, queryset=KnowledgeSource.objects.none(), required=False
    )
    handoff_team_id = serializers.PrimaryKeyRelatedField(
        source="handoff_team", queryset=Team.objects.none(), required=False, allow_null=True
    )

    class Meta:
        model = AIAgent
        fields = [
            "id",
            "name",
            "description",
            "instructions",
            "provider",
            "model",
            "effort",
            "max_output_tokens",
            "use_all_knowledge",
            "knowledge_source_ids",
            "retrieval_top_k",
            "min_relevance",
            "answer_only_from_knowledge",
            "tone",
            "greeting",
            "handoff_confidence_threshold",
            "handoff_on_no_knowledge",
            "handoff_keywords",
            "max_ai_replies",
            "handoff_team_id",
            "handoff_message",
            "allow_after_human_takeover",
            "enabled",
            "is_deployed",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "is_deployed", "created_at", "updated_at"]
        extra_kwargs = {
            "max_output_tokens": {"min_value": 256, "max_value": 32000},
            "retrieval_top_k": {"min_value": 1, "max_value": 20},
            "min_relevance": {"min_value": 0.0, "max_value": 1.0},
            "handoff_confidence_threshold": {"min_value": 0.0, "max_value": 1.0},
            "max_ai_replies": {"min_value": 1, "max_value": 100},
        }

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        workspace = self.context.get("workspace")
        if workspace is not None:  # foreign ids fail validation exactly like unknown ids
            self.fields["knowledge_source_ids"].child_relation.queryset = KnowledgeSource.objects.filter(
                workspace=workspace
            )
            self.fields["handoff_team_id"].queryset = Team.objects.filter(workspace=workspace)

    def validate_model(self, value: str) -> str:
        value = value.strip()
        if not value or len(value) > 100 or any(c.isspace() for c in value):
            raise serializers.ValidationError("Enter a valid model id.")
        return value

    def validate_handoff_keywords(self, value: list[str]) -> list[str]:
        cleaned = [v.strip().lower() for v in value if v.strip()]
        if len(cleaned) > 30:
            raise serializers.ValidationError("At most 30 keywords.")
        return list(dict.fromkeys(cleaned))

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        provider = attrs.get("provider")
        if provider and "model" not in attrs and (self.instance is None or self.instance.provider != provider):
            attrs["model"] = DEFAULT_MODELS[provider]
        return attrs


class ToolExecutionSerializer(serializers.ModelSerializer):
    class Meta:
        model = ToolExecution
        fields = ["id", "tool_name", "arguments", "result", "status", "latency_ms", "created_at"]
        read_only_fields = fields


class AIExecutionSerializer(serializers.ModelSerializer):
    tool_executions = ToolExecutionSerializer(many=True, read_only=True)
    agent_name = serializers.CharField(source="agent.name", default=None, read_only=True)

    class Meta:
        model = AIExecution
        fields = [
            "id",
            "agent",
            "agent_name",
            "source",
            "conversation",
            "status",
            "skip_reason",
            "provider",
            "model",
            "input_tokens",
            "output_tokens",
            "latency_ms",
            "confidence",
            "handoff_reason",
            "query",
            "answer",
            "retrieved",
            "steps",
            "error",
            "tool_executions",
            "created_at",
        ]
        read_only_fields = fields


class PlaygroundMessageSerializer(serializers.Serializer):
    role = serializers.ChoiceField(choices=["user", "assistant"])
    content = serializers.CharField(max_length=5000)


class PlaygroundRequestSerializer(serializers.Serializer):
    messages = PlaygroundMessageSerializer(many=True, min_length=1, max_length=40)

    def validate_messages(self, value: list[dict[str, str]]) -> list[dict[str, str]]:
        if value[-1]["role"] != "user":
            raise serializers.ValidationError("The last message must be from the user.")
        return value


class PlaygroundResponseSerializer(serializers.Serializer):
    execution_id = serializers.UUIDField()
    decision = serializers.CharField()
    answer = serializers.CharField(allow_blank=True)
    handoff_reason = serializers.CharField(allow_blank=True)
    confidence = serializers.FloatField(allow_null=True)
    sources = serializers.ListField()
    tool_calls = serializers.ListField()
    input_tokens = serializers.IntegerField()
    output_tokens = serializers.IntegerField()
    latency_ms = serializers.IntegerField()
    provider = serializers.CharField(allow_blank=True)
    model = serializers.CharField(allow_blank=True)
    steps = serializers.ListField()


class AIAgentViewSet(WorkspaceScopedViewMixin, viewsets.GenericViewSet):
    serializer_class = AIAgentSerializer
    lookup_value_converter = "uuid"
    pagination_class = None
    permission_by_action = {
        "list": Perm.AI_AGENTS_VIEW,
        "retrieve": Perm.AI_AGENTS_VIEW,
        "executions": Perm.AI_AGENTS_VIEW,
        "providers": Perm.AI_AGENTS_VIEW,
        "create": Perm.AI_AGENTS_MANAGE,
        "partial_update": Perm.AI_AGENTS_MANAGE,
        "destroy": Perm.AI_AGENTS_MANAGE,
        "deploy": Perm.AI_AGENTS_MANAGE,
        "undeploy": Perm.AI_AGENTS_MANAGE,
        "playground": Perm.AI_AGENTS_MANAGE,
    }

    def get_throttles(self) -> list[Any]:
        if self.action == "playground":
            self.throttle_scope = "ai_playground"
            return [ScopedRateThrottle()]
        return super().get_throttles()

    def get_queryset(self) -> QuerySet[AIAgent]:
        return AIAgent.objects.filter(workspace=self.workspace).prefetch_related("knowledge_sources").order_by("name")

    def get_serializer_context(self) -> dict[str, Any]:
        return {**super().get_serializer_context(), "workspace": self.workspace}

    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return Response(AIAgentSerializer(self.get_queryset(), many=True).data)

    def retrieve(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        agent = self.get_object()
        return Response({**AIAgentSerializer(agent).data, "stats": services.execution_stats(agent)})

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        agent = serializer.save(workspace=self.workspace, created_by=request.user)
        return Response(AIAgentSerializer(agent).data, status=status.HTTP_201_CREATED)

    def partial_update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = self.get_serializer(self.get_object(), data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        return Response(AIAgentSerializer(serializer.save()).data)

    def destroy(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        self.get_object().delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(request=None, responses={200: AIAgentSerializer})
    @action(detail=True, methods=["post"])
    def deploy(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return Response(AIAgentSerializer(services.deploy_agent(self.get_object())).data)

    @extend_schema(request=None, responses={200: AIAgentSerializer})
    @action(detail=True, methods=["post"])
    def undeploy(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return Response(AIAgentSerializer(services.undeploy_agent(self.get_object())).data)

    @extend_schema(request=PlaygroundRequestSerializer, responses={200: PlaygroundResponseSerializer})
    @action(detail=True, methods=["post"])
    def playground(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        agent = self.get_object()
        serializer = PlaygroundRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        execution, result = services.run_playground(agent=agent, messages=serializer.validated_data["messages"])
        return Response(
            {
                "execution_id": execution.id,
                "decision": result.decision,
                "answer": result.answer if result.decision == "answer" else agent.handoff_message,
                "handoff_reason": result.handoff_reason,
                "confidence": result.confidence,
                "sources": [
                    {"source_id": c.source_id, "title": c.source_title, "score": c.score, "excerpt": c.content[:300]}
                    for c in result.retrieved
                ],
                "tool_calls": [
                    {"name": t.name, "arguments": t.arguments, "status": t.status, "result": t.result}
                    for t in result.tool_calls
                ],
                "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens,
                "latency_ms": execution.latency_ms,
                "provider": result.provider,
                "model": result.model,
                "steps": result.steps,
            }
        )

    @extend_schema(responses={200: AIExecutionSerializer(many=True)})
    @action(detail=True, methods=["get"])
    def executions(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        qs = self.get_object().executions.prefetch_related("tool_executions").order_by("-created_at")
        if source := request.query_params.get("source"):
            qs = qs.filter(source=source)
        if status_ := request.query_params.get("status"):
            qs = qs.filter(status=status_)
        paginator = ConversationViewSet.pagination_class()
        page = paginator.paginate_queryset(qs, request, view=self)
        return paginator.get_paginated_response(AIExecutionSerializer(page, many=True).data)

    @action(detail=False, methods=["get"])
    def providers(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return Response(
            {
                "providers": [
                    {
                        "id": p.value,
                        "label": p.label,
                        "default_model": DEFAULT_MODELS[p],
                        **provider_status().get(p.value, {}),
                    }
                    for p in Provider
                ],
                "efforts": [{"id": e.value, "label": e.label} for e in Effort],
                "mock_fallback_enabled": provider_status()["mock_fallback_enabled"]["configured"],
            }
        )


class ConversationAIView(WorkspaceScopedViewMixin, APIView):
    """POST /workspaces/{ws}/conversations/{id}/ai/{summarize|take-over|resume}/"""

    permission_by_action = {"post": Perm.CONVERSATIONS_REPLY}

    @extend_schema(request=None, responses={200: dict})
    def post(self, request: Request, workspace_id: Any, conversation_id: Any, operation: str) -> Response:
        conversation = get_object_or_404(Conversation, id=conversation_id, workspace=self.workspace)
        actor = Actor.agent(request.user)
        if operation == "summarize":
            conversation = services.summarize_conversation(conversation=conversation, user=request.user)
        elif operation == "take-over":
            conversation = set_ai_state(conversation=conversation, state=AIState.PAUSED, actor=actor)
        elif operation == "resume":
            conversation = set_ai_state(conversation=conversation, state=AIState.ACTIVE, actor=actor)
        else:
            return Response(status=status.HTTP_404_NOT_FOUND)
        return Response(
            {
                "ai_state": conversation.ai_state,
                "ai_summary": conversation.ai_summary,
                "ai_summary_at": conversation.ai_summary_at,
            }
        )


class WorkspaceExecutionListView(WorkspaceScopedViewMixin, APIView):
    """GET /workspaces/{ws}/ai-executions/?conversation=… — AI activity for a conversation."""

    permission_by_action = {"get": Perm.CONVERSATIONS_VIEW}

    @extend_schema(responses={200: AIExecutionSerializer(many=True)})
    def get(self, request: Request, workspace_id: Any) -> Response:
        from common.text import parse_uuid

        qs = (
            AIExecution.objects.filter(workspace=self.workspace)
            .select_related("agent")
            .prefetch_related("tool_executions")
        )
        conv = parse_uuid(request.query_params.get("conversation"))
        qs = qs.filter(conversation_id=conv) if conv else qs.none()
        return Response(AIExecutionSerializer(qs.order_by("-created_at")[:50], many=True).data)
