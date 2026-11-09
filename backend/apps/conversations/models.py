from __future__ import annotations

import os
import uuid
from typing import Any

from django.conf import settings
from django.contrib.postgres.indexes import GinIndex
from django.db import models
from django.db.models import Q
from django.utils import timezone

from apps.customers.models import Customer
from apps.workspaces.models import Tag, Team, WorkspaceOwnedModel
from common.models import BaseModel


class ConversationStatus(models.TextChoices):
    OPEN = "open", "Open"
    PENDING = "pending", "Pending"
    RESOLVED = "resolved", "Resolved"
    CLOSED = "closed", "Closed"


class ConversationPriority(models.TextChoices):
    LOW = "low", "Low"
    NORMAL = "normal", "Normal"
    HIGH = "high", "High"
    URGENT = "urgent", "Urgent"


class Channel(models.TextChoices):
    WIDGET = "widget", "Website widget"
    DASHBOARD = "dashboard", "Started by agent"


class ActorType(models.TextChoices):
    CUSTOMER = "customer", "Customer"
    AGENT = "agent", "Agent"
    AI = "ai", "AI"
    SYSTEM = "system", "System"


class AIState(models.TextChoices):
    ACTIVE = "active", "AI active"
    PAUSED = "paused", "Human took over"
    HANDED_OFF = "handed_off", "Handed off to team"


class Conversation(WorkspaceOwnedModel):
    number = models.PositiveIntegerField(editable=False)
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name="conversations")
    subject = models.CharField(max_length=200, blank=True, default="")
    channel = models.CharField(max_length=20, choices=Channel.choices, default=Channel.WIDGET)
    status = models.CharField(max_length=20, choices=ConversationStatus.choices, default=ConversationStatus.OPEN)
    priority = models.CharField(
        max_length=20, choices=ConversationPriority.choices, default=ConversationPriority.NORMAL
    )
    # Current assignment (history lives in ConversationAssignment).
    assignee = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="assigned_conversations",
    )
    team = models.ForeignKey(Team, null=True, blank=True, on_delete=models.SET_NULL, related_name="conversations")
    tags = models.ManyToManyField(Tag, related_name="conversations", blank=True)
    # Denormalized for fast inbox listing/sorting; maintained by services.
    last_message_at = models.DateTimeField(default=timezone.now)
    last_message_preview = models.CharField(max_length=200, blank=True, default="")
    last_message_author_type = models.CharField(max_length=20, choices=ActorType.choices, blank=True, default="")
    last_customer_message_at = models.DateTimeField(null=True, blank=True)
    first_response_at = models.DateTimeField(null=True, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    # AI handling (Phase 3). The AI may only reply while ai_state is ACTIVE, unless the
    # deployed agent explicitly allows replying after a human takeover.
    ai_state = models.CharField(max_length=20, choices=AIState.choices, default=AIState.ACTIVE)
    ai_handoff_at = models.DateTimeField(null=True, blank=True)
    human_takeover_at = models.DateTimeField(null=True, blank=True)
    ai_summary = models.TextField(blank=True, default="")
    ai_summary_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-last_message_at"]
        constraints = [
            models.UniqueConstraint(fields=["workspace", "number"], name="conversation_unique_number_per_workspace"),
        ]
        indexes = [
            models.Index(fields=["workspace", "status", "-last_message_at"], name="conv_ws_status_last"),
            models.Index(fields=["workspace", "assignee", "status"], name="conv_ws_assignee_status"),
            models.Index(fields=["workspace", "team", "status"], name="conv_ws_team_status"),
            models.Index(fields=["customer", "-last_message_at"], name="conv_customer_last"),
        ]

    def __str__(self) -> str:
        return f"#{self.number}"


class MessageKind(models.TextChoices):
    REPLY = "reply", "Reply"  # visible to the customer
    NOTE = "note", "Internal note"  # visible to the team only


class Message(WorkspaceOwnedModel):
    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name="messages")
    kind = models.CharField(max_length=10, choices=MessageKind.choices, default=MessageKind.REPLY)
    author_type = models.CharField(max_length=20, choices=ActorType.choices)
    author_user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    author_customer = models.ForeignKey(
        Customer, null=True, blank=True, on_delete=models.SET_NULL, related_name="messages"
    )
    body = models.TextField(max_length=10000, blank=True, default="")

    class Meta:
        ordering = ["created_at"]
        indexes = [
            models.Index(fields=["conversation", "created_at"], name="message_conv_created"),
            GinIndex(fields=["body"], opclasses=["gin_trgm_ops"], name="message_body_trgm"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=~Q(kind="note") | Q(author_type__in=["agent", "system"]),
                name="message_note_authored_by_team",
            ),
        ]


def attachment_upload_to(instance: Attachment, filename: str) -> str:
    # Random path segment: storage keys are not guessable and never reuse user filenames as keys.
    ext = os.path.splitext(filename)[1].lower()[:10]
    return f"attachments/{instance.workspace_id}/{uuid.uuid4().hex}{ext}"


class Attachment(WorkspaceOwnedModel):
    """Privately stored file. Only served through an authorized download endpoint."""

    message = models.ForeignKey(Message, null=True, blank=True, on_delete=models.CASCADE, related_name="attachments")
    file = models.FileField(upload_to=attachment_upload_to, max_length=255)
    filename = models.CharField(max_length=255)
    content_type = models.CharField(max_length=100)
    size = models.PositiveIntegerField()
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        ordering = ["created_at"]


class ConversationEventType(models.TextChoices):
    CREATED = "created", "Created"
    STATUS_CHANGED = "status_changed", "Status changed"
    PRIORITY_CHANGED = "priority_changed", "Priority changed"
    ASSIGNED = "assigned", "Assigned"
    TEAM_ASSIGNED = "team_assigned", "Team assigned"
    TAGS_CHANGED = "tags_changed", "Tags changed"
    REOPENED = "reopened", "Reopened by customer"
    HANDOFF = "handoff", "AI handed off"
    HUMAN_TAKEOVER = "human_takeover", "Human took over"
    AI_RESUMED = "ai_resumed", "AI resumed"


class ConversationEvent(WorkspaceOwnedModel):
    """Append-only history of state changes on a conversation."""

    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name="events")
    type = models.CharField(max_length=30, choices=ConversationEventType.choices)
    actor_type = models.CharField(max_length=20, choices=ActorType.choices)
    actor_user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    data = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["created_at"]
        indexes = [models.Index(fields=["conversation", "created_at"], name="conv_event_conv_created")]

    def save(self, *args: Any, **kwargs: Any) -> None:
        if not self._state.adding:
            raise RuntimeError("ConversationEvent entries are append-only")
        super().save(*args, **kwargs)


class ConversationAssignment(WorkspaceOwnedModel):
    """Assignment history. The open row (ended_at IS NULL) mirrors Conversation.assignee/team."""

    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name="assignments")
    assignee = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    team = models.ForeignKey(Team, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    ended_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["conversation"], condition=Q(ended_at__isnull=True), name="conv_assignment_one_open"
            ),
        ]


class ConversationReadState(BaseModel):
    """Per-agent read marker; a conversation is unread when the customer wrote after last_read_at."""

    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name="read_states")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    last_read_at = models.DateTimeField()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["conversation", "user"], name="conv_read_state_unique"),
        ]
