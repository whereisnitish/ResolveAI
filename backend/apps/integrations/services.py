from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import time
import uuid
from typing import Any
from urllib.parse import urlsplit

from django.db import transaction
from django.utils import timezone

from apps.conversations.models import Conversation, Message
from apps.integrations.models import DeliveryStatus, Integration, IntegrationDelivery, IntegrationKind
from apps.workspaces.models import Workspace
from common import crypto
from common.safe_http import safe_request, validate_url

MAX_ATTEMPTS = 5
DISABLE_AFTER_FAILURES = 50


def create_integration(
    *, workspace: Workspace, kind: str, name: str, url: str, events: list[str], user: Any
) -> tuple[Integration, str]:
    """Returns (integration, signing_secret). The secret is shown to the user once."""
    url = validate_url(url)
    if kind == IntegrationKind.SLACK and urlsplit(url).hostname != "hooks.slack.com":
        raise ValueError("Slack incoming webhook URLs start with https://hooks.slack.com/")
    secret = f"whsec_{secrets.token_urlsafe(32)}" if kind == IntegrationKind.WEBHOOK else ""
    integration = Integration.objects.create(
        workspace=workspace,
        kind=kind,
        name=name,
        url_encrypted=crypto.encrypt(url),
        url_host=urlsplit(url).hostname or "",
        signing_secret_encrypted=crypto.encrypt(secret),
        events=events,
        created_by=user,
    )
    return integration, secret


def rotate_secret(integration: Integration) -> str:
    secret = f"whsec_{secrets.token_urlsafe(32)}"
    integration.signing_secret_encrypted = crypto.encrypt(secret)
    integration.save(update_fields=["signing_secret_encrypted", "updated_at"])
    return secret


def sign(secret: str, timestamp: int, body: bytes) -> str:
    """Header value ``t=<unix>,v1=<hex HMAC-SHA256(secret, f"{t}.{body}")>``; verify in constant time."""
    return f"t={timestamp},v1={hmac.new(secret.encode(), f'{timestamp}.'.encode() + body, hashlib.sha256).hexdigest()}"


def _conversation_payload(conv: Conversation) -> dict[str, Any]:
    c = conv.customer
    return {
        "id": str(conv.id),
        "number": conv.number,
        "status": conv.status,
        "priority": conv.priority,
        "channel": conv.channel,
        "assignee": {"id": str(conv.assignee_id), "email": conv.assignee.email} if conv.assignee else None,
        "team": {"id": str(conv.team_id), "name": conv.team.name} if conv.team else None,
        "customer": {"id": str(c.id), "name": c.display_name, "email": c.email or None},
    }


def build_event(event: str, conv: Conversation, message: Message | None = None) -> dict[str, Any]:
    data: dict[str, Any] = {"conversation": _conversation_payload(conv)}
    if message is not None:
        data["message"] = {"id": str(message.id), "author_type": message.author_type, "body": message.body[:4000]}
    return {
        "id": f"evt_{uuid.uuid4().hex}",
        "type": event,
        "created_at": timezone.now().isoformat(),
        "workspace_id": str(conv.workspace_id),
        "data": data,
    }


def slack_payload(event: dict[str, Any]) -> dict[str, Any]:
    conv = event["data"]["conversation"]
    title = {
        "conversation.created": "New conversation",
        "conversation.resolved": "Conversation resolved",
        "conversation.assigned": "Conversation assigned",
        "message.created": "New customer message",
    }.get(event["type"], event["type"])
    text = f"*{title}* #{conv['number']} from {conv['customer']['name']}"
    if msg := event["data"].get("message"):
        text += f"\n>{msg['body'][:300]}"
    return {"text": text}


def fan_out(
    event: str, conversation_id: str, message_id: str | None = None, test_integration: Integration | None = None
) -> list[IntegrationDelivery]:
    conv = Conversation.objects.select_related("customer", "assignee", "team").filter(id=conversation_id).first()
    if conv is None:
        return []
    message = Message.objects.filter(id=message_id, conversation=conv).first() if message_id else None
    targets = (
        [test_integration]
        if test_integration
        else Integration.objects.filter(workspace_id=conv.workspace_id, enabled=True, events__contains=[event])
    )
    from apps.integrations.tasks import deliver_task

    deliveries = []
    for integration in targets:
        payload = build_event(event, conv, message)
        delivery = IntegrationDelivery.objects.create(
            workspace_id=conv.workspace_id,
            organization_id=conv.organization_id,
            integration=integration,
            event=event,
            payload=payload,
        )
        deliveries.append(delivery)
        delivery_id = str(delivery.id)
        transaction.on_commit(lambda d=delivery_id: deliver_task.delay(d))
    return deliveries


def deliver(delivery_id: str) -> IntegrationDelivery | None:
    """One delivery attempt. Returns the delivery; raises RetryableDeliveryError to trigger a retry."""
    delivery = IntegrationDelivery.objects.select_related("integration").filter(id=delivery_id).first()
    if delivery is None or delivery.status == DeliveryStatus.SUCCEEDED:
        return delivery
    integration = delivery.integration
    delivery.attempts += 1
    url = crypto.decrypt(integration.url_encrypted)
    if integration.kind == IntegrationKind.SLACK:
        body = json.dumps(slack_payload(delivery.payload)).encode()
        headers = {"Content-Type": "application/json"}
    else:
        body = json.dumps(delivery.payload, separators=(",", ":")).encode()
        ts = int(time.time())
        headers = {
            "Content-Type": "application/json",
            "X-ResolveAI-Event": delivery.event,
            "X-ResolveAI-Delivery": str(delivery.id),
            "X-ResolveAI-Signature": sign(crypto.decrypt(integration.signing_secret_encrypted), ts, body),
        }
    ok = False
    try:
        response = safe_request("POST", url, content=body, headers=headers, timeout=10, max_bytes=64 * 1024)
        delivery.response_status = response.status_code
        ok = 200 <= response.status_code < 300
        delivery.error = "" if ok else f"HTTP {response.status_code}"
    except Exception as exc:
        delivery.error = str(exc)[:500]
    now = timezone.now()
    if ok:
        delivery.status = DeliveryStatus.SUCCEEDED
        delivery.delivered_at = now
        integration.consecutive_failures = 0
    else:
        delivery.status = DeliveryStatus.FAILED if delivery.attempts >= MAX_ATTEMPTS else DeliveryStatus.PENDING
        integration.consecutive_failures += 1
        if integration.consecutive_failures >= DISABLE_AFTER_FAILURES:
            integration.enabled = False  # stop hammering a dead endpoint
    integration.last_delivery_at = now
    integration.save(update_fields=["consecutive_failures", "enabled", "last_delivery_at", "updated_at"])
    delivery.save()
    if delivery.status == DeliveryStatus.PENDING:
        raise RetryableDeliveryError(delivery.error)
    return delivery


class RetryableDeliveryError(Exception):
    pass
