from __future__ import annotations

from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from django.db import models
from django.db.models import Q

from apps.workspaces.models import WorkspaceOwnedModel

DEFAULT_HANDOFF_KEYWORDS = [
    "human",
    "agent",
    "person",
    "representative",
    "real person",
    "talk to someone",
    "speak to someone",
    "customer service",
]


class Provider(models.TextChoices):
    ANTHROPIC = "anthropic", "Anthropic (Claude)"
    OPENAI = "openai", "OpenAI"
    MOCK = "mock", "Mock (offline, deterministic)"


class Effort(models.TextChoices):
    LOW = "low", "Low (fastest)"
    MEDIUM = "medium", "Medium"
    HIGH = "high", "High (most thorough)"


DEFAULT_MODELS = {
    Provider.ANTHROPIC: "claude-opus-5-5",
    Provider.OPENAI: "gpt-5.5",
    Provider.MOCK: "mock-1",
}


class AIAgent(WorkspaceOwnedModel):
    name = models.CharField(max_length=80)
    description = models.CharField(max_length=300, blank=True, default="")
    # Private: never sent to visitors. Checked for leakage in AI answers.
    instructions = models.TextField(max_length=20_000, blank=True, default="")
    provider = models.CharField(max_length=20, choices=Provider.choices, default=Provider.ANTHROPIC)
    model = models.CharField(max_length=100, default=DEFAULT_MODELS[Provider.ANTHROPIC])
    effort = models.CharField(max_length=10, choices=Effort.choices, default=Effort.MEDIUM)
    max_output_tokens = models.PositiveIntegerField(default=8000)
    # Knowledge
    use_all_knowledge = models.BooleanField(default=True)
    knowledge_sources = models.ManyToManyField("knowledge.KnowledgeSource", blank=True, related_name="agents")
    retrieval_top_k = models.PositiveSmallIntegerField(default=5)
    min_relevance = models.FloatField(default=0.15)
    answer_only_from_knowledge = models.BooleanField(default=True)
    # Response behaviour
    tone = models.CharField(max_length=200, blank=True, default="Friendly, concise and professional.")
    greeting = models.CharField(max_length=300, blank=True, default="")
    # Handoff rules
    handoff_confidence_threshold = models.FloatField(default=0.5)
    handoff_on_no_knowledge = models.BooleanField(default=True)
    handoff_keywords = ArrayField(models.CharField(max_length=60), default=list, blank=True)
    max_ai_replies = models.PositiveSmallIntegerField(default=10)
    handoff_team = models.ForeignKey(
        "workspaces.Team", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    handoff_message = models.CharField(
        max_length=300, default="I'm connecting you with a member of our team. They'll reply here shortly."
    )
    allow_after_human_takeover = models.BooleanField(default=False)
    # Lifecycle
    enabled = models.BooleanField(default=True)
    is_deployed = models.BooleanField(default=False)  # answers widget conversations
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["workspace"], condition=Q(is_deployed=True), name="ai_agent_one_deployed_per_workspace"
            ),
        ]

    def __str__(self) -> str:
        return self.name


class ExecutionSource(models.TextChoices):
    CONVERSATION = "conversation", "Conversation"
    PLAYGROUND = "playground", "Playground"
    SUMMARY = "summary", "Summary"


class ExecutionStatus(models.TextChoices):
    ANSWERED = "answered", "Answered"
    HANDED_OFF = "handed_off", "Handed off"
    SKIPPED = "skipped", "Skipped"
    QUOTA_EXCEEDED = "quota_exceeded", "Quota exceeded"
    FAILED = "failed", "Failed"


class AIExecution(WorkspaceOwnedModel):
    agent = models.ForeignKey(AIAgent, null=True, blank=True, on_delete=models.SET_NULL, related_name="executions")
    source = models.CharField(max_length=20, choices=ExecutionSource.choices)
    conversation = models.ForeignKey(
        "conversations.Conversation", null=True, blank=True, on_delete=models.CASCADE, related_name="ai_executions"
    )
    trigger_message = models.ForeignKey(
        "conversations.Message", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    response_message = models.ForeignKey(
        "conversations.Message", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    status = models.CharField(max_length=20, choices=ExecutionStatus.choices)
    skip_reason = models.CharField(max_length=60, blank=True, default="")
    provider = models.CharField(max_length=20, blank=True, default="")
    model = models.CharField(max_length=100, blank=True, default="")
    input_tokens = models.PositiveIntegerField(default=0)
    output_tokens = models.PositiveIntegerField(default=0)
    latency_ms = models.PositiveIntegerField(default=0)
    confidence = models.FloatField(null=True, blank=True)
    handoff_reason = models.CharField(max_length=200, blank=True, default="")
    query = models.TextField(blank=True, default="")
    answer = models.TextField(blank=True, default="")
    retrieved = models.JSONField(default=list, blank=True)  # [{chunk_id, source_id, title, score}]
    steps = models.JSONField(default=list, blank=True)  # graph trace [{node, ms, note}]
    error = models.CharField(max_length=500, blank=True, default="")

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["workspace", "-created_at"], name="aiexec_ws_created"),
            models.Index(fields=["agent", "-created_at"], name="aiexec_agent_created"),
        ]


class ToolExecution(WorkspaceOwnedModel):
    execution = models.ForeignKey(AIExecution, on_delete=models.CASCADE, related_name="tool_executions")
    tool_name = models.CharField(max_length=60)
    arguments = models.JSONField(default=dict, blank=True)
    result = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=20, default="succeeded")
    latency_ms = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["created_at"]
