"""Workflow definition schema, condition evaluation and action execution.

Every action runs through the normal service layer with a system actor whose
event source is "workflow", so workflows never trigger other workflows (loops).
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from django.db import IntegrityError, transaction
from django.db.models import Count, Q
from django.utils import timezone
from rest_framework import serializers

from apps.conversations import services as conv_services
from apps.conversations.models import (
    ActorType,
    Conversation,
    ConversationPriority,
    ConversationStatus,
    Message,
)
from apps.tenancy.access import workspace_users
from apps.workflows.models import Trigger, Workflow, WorkflowExecution
from apps.workspaces.models import Tag, Team, Workspace
from common.rbac import Perm

logger = logging.getLogger(__name__)

FIELDS = {
    "channel": "Channel",
    "priority": "Priority",
    "status": "Status",
    "customer.is_anonymous": "Customer is anonymous",
    "customer.email": "Customer email",
    "message.text": "Message text",
    "conversation.tags": "Conversation tags",
    "conversation.assigned": "Is assigned",
}
OPERATORS = {"eq", "neq", "contains", "not_contains", "in", "is_true", "is_false"}
ACTIONS = {
    "assign_user": ["user_id"],
    "assign_team": ["team_id"],
    "assign_round_robin": ["team_id"],
    "add_tag": ["tag_id"],
    "set_priority": ["priority"],
    "set_status": ["status"],
    "send_reply": ["body"],
    "add_note": ["body"],
}
MAX_ACTIONS = 10
MAX_RULES = 10


# ---------------------------------------------------------------------------
# Validation (used by the API serializer)
# ---------------------------------------------------------------------------
def validate_definition(
    workspace: Workspace, trigger: str, trigger_config: dict, conditions: dict, actions: list
) -> None:
    errors: dict[str, list[str]] = {}
    if trigger == Trigger.CONVERSATION_UNANSWERED:
        minutes = trigger_config.get("minutes")
        if not isinstance(minutes, int) or not 1 <= minutes <= 10080:
            errors["trigger_config"] = ["minutes must be an integer between 1 and 10080."]
    if not isinstance(conditions, dict):
        errors["conditions"] = ["Must be an object."]
    else:
        rules = conditions.get("rules", [])
        if (
            conditions.get("match", "all") not in ("all", "any")
            or not isinstance(rules, list)
            or len(rules) > MAX_RULES
        ):
            errors["conditions"] = [f"match must be all/any and rules a list of at most {MAX_RULES}."]
        else:
            for n, rule in enumerate(rules):
                if (
                    not isinstance(rule, dict)
                    or rule.get("field") not in FIELDS
                    or rule.get("operator") not in OPERATORS
                ):
                    errors.setdefault("conditions", []).append(f"Rule {n + 1}: unknown field or operator.")
    if not isinstance(actions, list) or not 1 <= len(actions) <= MAX_ACTIONS:
        errors["actions"] = [f"Add between 1 and {MAX_ACTIONS} actions."]
    else:
        for n, act in enumerate(actions):
            problem = _validate_action(workspace, act)
            if problem:
                errors.setdefault("actions", []).append(f"Action {n + 1}: {problem}")
    if errors:
        raise serializers.ValidationError(errors)


def _validate_action(workspace: Workspace, act: Any) -> str | None:
    if not isinstance(act, dict) or act.get("type") not in ACTIONS:
        return "unknown action type."
    missing = [k for k in ACTIONS[act["type"]] if not act.get(k)]
    if missing:
        return f"missing {', '.join(missing)}."
    t = act["type"]
    if (
        t == "assign_user"
        and not workspace_users(workspace, with_permission=Perm.CONVERSATIONS_REPLY).filter(id=act["user_id"]).exists()
    ):
        return "user can't be assigned in this workspace."
    if (
        t in ("assign_team", "assign_round_robin")
        and not Team.objects.filter(workspace=workspace, id=act["team_id"]).exists()
    ):
        return "team not found."
    if t == "add_tag" and not Tag.objects.filter(workspace=workspace, id=act["tag_id"]).exists():
        return "tag not found."
    if t == "set_priority" and act["priority"] not in ConversationPriority.values:
        return "invalid priority."
    if t == "set_status" and act["status"] not in ConversationStatus.values:
        return "invalid status."
    if t in ("send_reply", "add_note") and (not isinstance(act["body"], str) or len(act["body"]) > 2000):
        return "body must be text up to 2000 characters."
    return None


# ---------------------------------------------------------------------------
# Conditions
# ---------------------------------------------------------------------------
def _field_value(field: str, conv: Conversation, message: Message | None) -> Any:
    return {
        "channel": lambda: conv.channel,
        "priority": lambda: conv.priority,
        "status": lambda: conv.status,
        "customer.is_anonymous": lambda: conv.customer.is_anonymous,
        "customer.email": lambda: conv.customer.email,
        "message.text": lambda: message.body if message else "",
        "conversation.tags": lambda: [t.name.lower() for t in conv.tags.all()],
        "conversation.assigned": lambda: conv.assignee_id is not None,
    }[field]()


def _check(rule: dict[str, Any], conv: Conversation, message: Message | None) -> bool:
    value = _field_value(rule["field"], conv, message)
    expected = rule.get("value")
    op = rule["operator"]
    if op == "is_true":
        return bool(value)
    if op == "is_false":
        return not value
    if isinstance(value, list):
        hay = value
        needle = str(expected).lower()
        return {"contains": needle in hay, "not_contains": needle not in hay}.get(op, False)
    text, exp = str(value or "").lower(), expected
    if op == "eq":
        return text == str(exp).lower()
    if op == "neq":
        return text != str(exp).lower()
    if op == "in":
        return text in [str(v).lower() for v in (exp if isinstance(exp, list) else [exp])]
    # contains / not_contains: comma-separated alternatives, any match
    terms = [t.strip().lower() for t in (exp if isinstance(exp, list) else str(exp).split(",")) if str(t).strip()]
    hit = any(term in text for term in terms)
    return hit if op == "contains" else not hit


def conditions_match(workflow: Workflow, conv: Conversation, message: Message | None) -> bool:
    rules = (workflow.conditions or {}).get("rules", [])
    if not rules:
        return True
    results = (_check(r, conv, message) for r in rules)
    return all(results) if workflow.conditions.get("match", "all") == "all" else any(results)


# ---------------------------------------------------------------------------
# Actions
# ---------------------------------------------------------------------------
def _least_loaded_member(team: Team) -> Any:
    members = workspace_users(team.workspace, with_permission=Perm.CONVERSATIONS_REPLY).filter(support_teams=team)
    return (
        members.annotate(
            open_count=Count(
                "assigned_conversations",
                filter=Q(
                    assigned_conversations__workspace=team.workspace,
                    assigned_conversations__status__in=[ConversationStatus.OPEN, ConversationStatus.PENDING],
                ),
            )
        )
        .order_by("open_count", "date_joined")
        .first()
    )


def _apply(action: dict[str, Any], conv: Conversation) -> str:
    actor = conv_services.Actor.system(source="workflow")
    t = action["type"]
    ws = conv.workspace
    if t == "assign_user":
        user = workspace_users(ws, with_permission=Perm.CONVERSATIONS_REPLY).filter(id=action["user_id"]).first()
        if user is None:
            raise ValueError("user no longer assignable")
        conv_services.assign_conversation(conversation=conv, actor=actor, assignee=user)
        return f"assigned to {user.email}"
    if t in ("assign_team", "assign_round_robin"):
        team = Team.objects.get(workspace=ws, id=action["team_id"])
        if t == "assign_team":
            conv_services.assign_conversation(conversation=conv, actor=actor, team=team)
            return f"routed to {team.name}"
        member = _least_loaded_member(team)
        conv_services.assign_conversation(conversation=conv, actor=actor, team=team, assignee=member)
        return f"round-robin to {member.email if member else 'nobody (team empty)'}"
    if t == "add_tag":
        tag = Tag.objects.get(workspace=ws, id=action["tag_id"])
        ids = [str(i) for i in conv.tags.values_list("id", flat=True)]
        if str(tag.id) not in ids:
            conv_services.update_conversation(conversation=conv, data={"tag_ids": [*ids, str(tag.id)]}, actor=actor)
        return f"tagged {tag.name}"
    if t == "set_priority":
        conv_services.update_conversation(conversation=conv, data={"priority": action["priority"]}, actor=actor)
        return f"priority {action['priority']}"
    if t == "set_status":
        conv_services.update_conversation(conversation=conv, data={"status": action["status"]}, actor=actor)
        return f"status {action['status']}"
    if t == "send_reply":
        conv_services.post_message(conversation=conv, actor=actor, body=action["body"])
        return "reply sent"
    if t == "add_note":
        conv_services.post_message(conversation=conv, actor=actor, body=action["body"], kind="note")
        return "note added"
    raise ValueError(f"unknown action {t}")


def run_workflow(
    workflow: Workflow, conv: Conversation, message: Message | None, dedupe_key: str
) -> WorkflowExecution | None:
    if not conditions_match(workflow, conv, message):
        return None
    try:
        with transaction.atomic():
            execution = WorkflowExecution.objects.create(
                workspace_id=conv.workspace_id,
                organization_id=conv.organization_id,
                workflow=workflow,
                conversation=conv,
                trigger=workflow.trigger,
                status="running",
                dedupe_key=dedupe_key[:200],
            )
    except IntegrityError:
        return None  # already ran for this occurrence
    results, failures = [], 0
    for action in workflow.actions:
        try:
            with transaction.atomic():
                note = _apply(action, conv)
            results.append({"type": action["type"], "status": "succeeded", "detail": note})
        except Exception as exc:
            failures += 1
            logger.warning(
                "workflow_action_failed workflow=%s action=%s error=%s", workflow.id, action.get("type"), exc
            )
            results.append({"type": action.get("type"), "status": "failed", "detail": str(exc)[:200]})
        conv.refresh_from_db()
    execution.results = results
    execution.status = "succeeded" if failures == 0 else "failed" if failures == len(results) else "partial"
    execution.save(update_fields=["results", "status", "updated_at"])
    Workflow.objects.filter(pk=workflow.pk).update(run_count=workflow.run_count + 1, last_run_at=timezone.now())
    return execution


def dispatch(trigger: str, conversation_id: str, message_id: str | None = None, occurrence: str = "") -> int:
    conv = Conversation.objects.select_related("workspace", "customer").filter(id=conversation_id).first()
    if conv is None:
        return 0
    message = Message.objects.filter(id=message_id, conversation=conv).first() if message_id else None
    ran = 0
    for wf in Workflow.objects.filter(workspace=conv.workspace, trigger=trigger, enabled=True):
        key = f"{wf.id}:{conv.id}:{trigger}:{occurrence or message_id or ''}"
        if run_workflow(wf, conv, message, key):
            ran += 1
    return ran


def scan_unanswered() -> int:
    """Periodic: run 'customer waiting' workflows for conversations with no reply after N minutes."""
    now = timezone.now()
    ran = 0
    for wf in Workflow.objects.filter(trigger=Trigger.CONVERSATION_UNANSWERED, enabled=True).select_related(
        "workspace"
    ):
        minutes = int(wf.trigger_config.get("minutes", 15))
        cutoff = now - timedelta(minutes=minutes)
        waiting = Conversation.objects.filter(
            workspace=wf.workspace,
            status__in=[ConversationStatus.OPEN, ConversationStatus.PENDING],
            last_message_author_type=ActorType.CUSTOMER,
            last_customer_message_at__lte=cutoff,
            last_customer_message_at__gte=cutoff - timedelta(days=7),
        ).select_related("customer", "workspace")[:500]
        for conv in waiting:
            occurrence = conv.last_customer_message_at.isoformat() if conv.last_customer_message_at else ""
            if run_workflow(wf, conv, None, f"{wf.id}:{conv.id}:unanswered:{occurrence}"):
                ran += 1
    return ran
