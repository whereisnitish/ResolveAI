"""Conversation business logic. Views and the widget API call into this module only."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from django.db import transaction
from django.db.models import F
from django.utils import timezone

from apps.accounts.models import User
from apps.conversations.models import (
    ActorType,
    AIState,
    Attachment,
    Channel,
    Conversation,
    ConversationAssignment,
    ConversationEvent,
    ConversationEventType,
    ConversationReadState,
    ConversationStatus,
    Message,
    MessageKind,
)
from apps.customers.models import Customer
from apps.customers.services import resolve_tags
from apps.realtime.publish import publish_visitor, publish_workspace
from apps.tenancy.access import user_has_workspace_permission
from apps.workspaces.models import Team, Workspace
from common import events
from common.exceptions import ServiceError
from common.files import ValidatedUpload
from common.rbac import Perm

PREVIEW_LENGTH = 200
MAX_BODY_LENGTH = 10000
REOPEN_ON_CUSTOMER_REPLY = {ConversationStatus.RESOLVED, ConversationStatus.CLOSED, ConversationStatus.PENDING}


@dataclass(frozen=True)
class Actor:
    """Who performs an action: an agent (user), the customer, or the system."""

    type: str
    user: User | None = None
    customer: Customer | None = None

    @classmethod
    def agent(cls, user: User) -> Actor:
        return cls(ActorType.AGENT, user=user)

    @classmethod
    def of_customer(cls, customer: Customer) -> Actor:
        return cls(ActorType.CUSTOMER, customer=customer)

    @classmethod
    def ai(cls) -> Actor:
        return cls(ActorType.AI)

    @classmethod
    def system(cls, source: str = "system") -> Actor:
        return cls(ActorType.SYSTEM, source=source)

    source: str = ""

    @property
    def event_source(self) -> str:
        """Origin reported on domain events (lets subscribers avoid feedback loops)."""
        if self.source:
            return self.source
        return {ActorType.AGENT: "user", ActorType.CUSTOMER: "customer", ActorType.AI: "ai"}.get(self.type, "system")


def _next_number(workspace: Workspace) -> int:
    # Row lock serializes number allocation per workspace without a global sequence.
    ws = Workspace.objects.select_for_update().only("id", "conversation_seq").get(pk=workspace.pk)
    ws.conversation_seq = F("conversation_seq") + 1
    ws.save(update_fields=["conversation_seq"])
    ws.refresh_from_db(fields=["conversation_seq"])
    return ws.conversation_seq


def _event(conversation: Conversation, type_: str, actor: Actor, **data: Any) -> ConversationEvent:
    return ConversationEvent.objects.create(
        workspace_id=conversation.workspace_id,
        organization_id=conversation.organization_id,
        conversation=conversation,
        type=type_,
        actor_type=actor.type,
        actor_user=actor.user,
        data=data,
    )


def _publish_conversation(conversation: Conversation, event_type: str = "conversation.updated") -> None:
    publish_workspace(conversation.workspace_id, {"type": event_type, "conversation_id": str(conversation.id)})


def _clean_body(body: str) -> str:
    body = (body or "").strip()
    if len(body) > MAX_BODY_LENGTH:
        raise ServiceError(f"Message is too long (max {MAX_BODY_LENGTH} characters).", code="message_too_long")
    return body


# -----------------------------------------------------------------------------
# Creation & messages
# -----------------------------------------------------------------------------
@transaction.atomic
def start_conversation(
    *,
    workspace: Workspace,
    customer: Customer,
    actor: Actor,
    body: str,
    subject: str = "",
    channel: str = Channel.WIDGET,
    files: Sequence[ValidatedUpload] = (),
) -> tuple[Conversation, Message]:
    if customer.workspace_id != workspace.id:
        raise ServiceError("Customer not found.", code="invalid_customer", status_code=404)
    body = _clean_body(body)
    if not body and not files:
        raise ServiceError("Message can't be empty.", code="empty_message")
    conversation = Conversation.objects.create(
        workspace=workspace,
        number=_next_number(workspace),
        customer=customer,
        subject=subject.strip()[:200],
        channel=channel,
    )
    _event(conversation, ConversationEventType.CREATED, actor, channel=channel)
    events.emit(
        "conversation.created",
        conversation_id=str(conversation.id),
        workspace_id=str(workspace.id),
        channel=channel,
        source=actor.event_source,
    )
    message = post_message(conversation=conversation, actor=actor, body=body, files=files, _new=True)
    _publish_conversation(conversation, "conversation.created")
    return conversation, message


@transaction.atomic
def post_message(
    *,
    conversation: Conversation,
    actor: Actor,
    body: str,
    kind: str = MessageKind.REPLY,
    files: Sequence[ValidatedUpload] = (),
    _new: bool = False,
) -> Message:
    body = _clean_body(body)
    if not body and not files:
        raise ServiceError("Message can't be empty.", code="empty_message")
    if kind == MessageKind.NOTE and actor.type not in (ActorType.AGENT, ActorType.SYSTEM):
        raise ServiceError("Only team members can write internal notes.", code="invalid_kind", status_code=403)

    conv = Conversation.objects.select_for_update().get(pk=conversation.pk)
    message = Message.objects.create(
        workspace_id=conv.workspace_id,
        organization_id=conv.organization_id,
        conversation=conv,
        kind=kind,
        author_type=actor.type,
        author_user=actor.user,
        author_customer=actor.customer,
        body=body,
    )
    for upload in files:
        Attachment.objects.create(
            workspace_id=conv.workspace_id,
            organization_id=conv.organization_id,
            message=message,
            file=upload.file,
            filename=upload.filename,
            content_type=upload.content_type,
            size=upload.size,
            uploaded_by=actor.user,
        )

    now = message.created_at
    update_fields: list[str] = []
    if kind == MessageKind.REPLY:
        # Internal notes don't reorder the inbox or change what the customer sees.
        conv.last_message_at = now
        conv.last_message_preview = (body or f"📎 {files[0].filename}")[:PREVIEW_LENGTH]
        conv.last_message_author_type = actor.type
        update_fields += ["last_message_at", "last_message_preview", "last_message_author_type"]
        if actor.type == ActorType.CUSTOMER:
            conv.last_customer_message_at = now
            update_fields.append("last_customer_message_at")
            if not _new and conv.status in REOPEN_ON_CUSTOMER_REPLY:
                previous = conv.status
                conv.status = ConversationStatus.OPEN
                conv.resolved_at = None
                update_fields += ["status", "resolved_at"]
                _event(conv, ConversationEventType.REOPENED, actor, **{"from": previous, "to": "open"})
        elif actor.type == ActorType.AGENT:
            if conv.first_response_at is None:
                conv.first_response_at = now
                update_fields.append("first_response_at")
            # A human replying to the customer takes control: the AI stops answering.
            if conv.ai_state == AIState.ACTIVE:
                conv.ai_state = AIState.PAUSED
                conv.human_takeover_at = now
                update_fields += ["ai_state", "human_takeover_at"]
                _event(conv, ConversationEventType.HUMAN_TAKEOVER, actor)
    if update_fields:
        conv.save(update_fields=[*update_fields, "updated_at"])

    events.emit(
        "message.created",
        conversation_id=str(conv.id),
        workspace_id=str(conv.workspace_id),
        message_id=str(message.id),
        author_type=actor.type,
        kind=kind,
        source=actor.event_source,
    )

    publish_workspace(
        conv.workspace_id,
        {"type": "message.created", "conversation_id": str(conv.id), "message_id": str(message.id), "kind": kind},
    )
    if kind == MessageKind.REPLY:
        from apps.widget.serializers import widget_message_payload  # local import: widget depends on us

        publish_visitor(
            conv.customer_id,
            {"type": "message.created", "conversation_id": str(conv.id), "message": widget_message_payload(message)},
        )
    return message


# -----------------------------------------------------------------------------
# State changes
# -----------------------------------------------------------------------------
@transaction.atomic
def update_conversation(*, conversation: Conversation, data: dict[str, Any], actor: Actor) -> Conversation:
    conv = Conversation.objects.select_for_update().get(pk=conversation.pk)
    changed: list[str] = []

    if "status" in data and data["status"] != conv.status:
        previous = conv.status
        conv.status = data["status"]
        if conv.status in (ConversationStatus.RESOLVED, ConversationStatus.CLOSED):
            conv.resolved_at = conv.resolved_at or timezone.now()
        else:
            conv.resolved_at = None
        changed += ["status", "resolved_at"]
        _event(conv, ConversationEventType.STATUS_CHANGED, actor, **{"from": previous, "to": conv.status})
        events.emit(
            "conversation.status_changed",
            conversation_id=str(conv.id),
            workspace_id=str(conv.workspace_id),
            source=actor.event_source,
            **{"from": previous, "to": conv.status},
        )

    if "priority" in data and data["priority"] != conv.priority:
        previous = conv.priority
        conv.priority = data["priority"]
        changed.append("priority")
        _event(conv, ConversationEventType.PRIORITY_CHANGED, actor, **{"from": previous, "to": conv.priority})

    if "subject" in data and data["subject"] != conv.subject:
        conv.subject = data["subject"][:200]
        changed.append("subject")

    if changed:
        conv.save(update_fields=[*changed, "updated_at"])

    if "tag_ids" in data:
        tags = resolve_tags(conv.workspace, data["tag_ids"])
        before = {t.id: t.name for t in conv.tags.all()}
        after = {t.id: t.name for t in tags}
        if before.keys() != after.keys():
            conv.tags.set(tags)
            _event(
                conv,
                ConversationEventType.TAGS_CHANGED,
                actor,
                added=sorted(name for tid, name in after.items() if tid not in before),
                removed=sorted(name for tid, name in before.items() if tid not in after),
            )
            changed.append("tags")

    if changed:
        _publish_conversation(conv)
    return conv


_UNSET: Any = object()


@transaction.atomic
def assign_conversation(
    *,
    conversation: Conversation,
    actor: Actor,
    assignee: User | None = _UNSET,
    team: Team | None = _UNSET,
) -> Conversation:
    """Change assignee and/or team. Omitted arguments keep their current value."""
    conv = Conversation.objects.select_for_update().get(pk=conversation.pk)
    workspace = conv.workspace
    new_assignee = conv.assignee if assignee is _UNSET else assignee
    new_team = conv.team if team is _UNSET else team

    assignee_changed = new_assignee is not None and new_assignee != conv.assignee
    if assignee_changed and not user_has_workspace_permission(new_assignee, workspace, Perm.CONVERSATIONS_REPLY):
        raise ServiceError("That person can't be assigned conversations in this workspace.", code="invalid_assignee")
    if new_team is not None and new_team.workspace_id != workspace.id:
        raise ServiceError("Team not found.", code="invalid_team")

    if new_assignee == conv.assignee and new_team == conv.team:
        return conv

    ConversationAssignment.objects.filter(conversation=conv, ended_at__isnull=True).update(ended_at=timezone.now())
    if new_assignee is not None or new_team is not None:
        ConversationAssignment.objects.create(
            workspace=workspace,
            conversation=conv,
            assignee=new_assignee,
            team=new_team,
            assigned_by=actor.user,
        )
    if new_assignee != conv.assignee:
        _event(
            conv,
            ConversationEventType.ASSIGNED,
            actor,
            assignee_id=str(new_assignee.id) if new_assignee else None,
            assignee_name=new_assignee.get_full_name() if new_assignee else None,
        )
    if new_team != conv.team:
        _event(
            conv,
            ConversationEventType.TEAM_ASSIGNED,
            actor,
            team_id=str(new_team.id) if new_team else None,
            team_name=new_team.name if new_team else None,
        )
    conv.assignee = new_assignee
    conv.team = new_team
    conv.save(update_fields=["assignee", "team", "updated_at"])
    events.emit(
        "conversation.assigned",
        conversation_id=str(conv.id),
        workspace_id=str(conv.workspace_id),
        assignee_id=str(new_assignee.id) if new_assignee else None,
        team_id=str(new_team.id) if new_team else None,
        source=actor.event_source,
    )
    _publish_conversation(conv)
    return conv


def mark_read(*, conversation: Conversation, user: User) -> None:
    ConversationReadState.objects.update_or_create(
        conversation=conversation, user=user, defaults={"last_read_at": timezone.now()}
    )


# -----------------------------------------------------------------------------
# AI handling state
# -----------------------------------------------------------------------------
_AI_TRANSITION_EVENTS = {
    AIState.PAUSED: ConversationEventType.HUMAN_TAKEOVER,
    AIState.ACTIVE: ConversationEventType.AI_RESUMED,
    AIState.HANDED_OFF: ConversationEventType.HANDOFF,
}


@transaction.atomic
def set_ai_state(*, conversation: Conversation, state: str, actor: Actor, reason: str = "") -> Conversation:
    conv = Conversation.objects.select_for_update().get(pk=conversation.pk)
    if conv.ai_state == state:
        return conv
    now = timezone.now()
    conv.ai_state = state
    fields = ["ai_state", "updated_at"]
    if state == AIState.PAUSED:
        conv.human_takeover_at = now
        fields.append("human_takeover_at")
    elif state == AIState.HANDED_OFF:
        conv.ai_handoff_at = now
        fields.append("ai_handoff_at")
    conv.save(update_fields=fields)
    _event(conv, _AI_TRANSITION_EVENTS[state], actor, **({"reason": reason} if reason else {}))
    _publish_conversation(conv)
    return conv
