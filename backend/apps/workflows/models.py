from __future__ import annotations

from django.conf import settings
from django.db import models

from apps.workspaces.models import WorkspaceOwnedModel


class Trigger(models.TextChoices):
    CONVERSATION_CREATED = "conversation_created", "New conversation"
    CUSTOMER_MESSAGE = "customer_message", "Customer sends a message"
    CONVERSATION_RESOLVED = "conversation_resolved", "Conversation resolved"
    CONVERSATION_UNANSWERED = "conversation_unanswered", "Customer waiting without a reply"


class Workflow(WorkspaceOwnedModel):
    """A declarative automation: WHEN trigger, IF conditions, THEN actions.

    conditions: {"match": "all"|"any", "rules": [{"field", "operator", "value"}]}
    actions:    [{"type": "...", ...params}]
    Both are validated against a fixed schema (apps.workflows.engine) — no code execution.
    """

    name = models.CharField(max_length=120)
    description = models.CharField(max_length=300, blank=True, default="")
    enabled = models.BooleanField(default=True)
    trigger = models.CharField(max_length=40, choices=Trigger.choices)
    trigger_config = models.JSONField(default=dict, blank=True)  # e.g. {"minutes": 15}
    conditions = models.JSONField(default=dict, blank=True)
    actions = models.JSONField(default=list)
    position = models.PositiveIntegerField(default=0)
    run_count = models.PositiveIntegerField(default=0)
    last_run_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        ordering = ["position", "created_at"]
        indexes = [models.Index(fields=["workspace", "trigger", "enabled"], name="workflow_ws_trigger")]

    def __str__(self) -> str:
        return self.name


class WorkflowExecution(WorkspaceOwnedModel):
    workflow = models.ForeignKey(Workflow, on_delete=models.CASCADE, related_name="executions")
    conversation = models.ForeignKey(
        "conversations.Conversation", null=True, blank=True, on_delete=models.CASCADE, related_name="+"
    )
    trigger = models.CharField(max_length=40, choices=Trigger.choices)
    status = models.CharField(max_length=20)  # succeeded | failed | partial
    results = models.JSONField(default=list, blank=True)
    error = models.CharField(max_length=500, blank=True, default="")
    # One run per workflow per triggering occurrence (makes retries and periodic scans idempotent).
    dedupe_key = models.CharField(max_length=200, unique=True)

    class Meta:
        ordering = ["-created_at"]
