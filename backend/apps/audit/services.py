from __future__ import annotations

import logging
import uuid
from typing import Any

from django.conf import settings
from django.http import HttpRequest

from apps.audit.models import AuditLog
from common.middleware import get_request_id

logger = logging.getLogger(__name__)


class AuditAction:
    USER_REGISTERED = "user.registered"
    USER_LOGIN = "user.login"
    USER_LOGIN_FAILED = "user.login_failed"
    USER_LOGOUT = "user.logout"
    USER_EMAIL_VERIFIED = "user.email_verified"
    USER_PASSWORD_RESET_REQUESTED = "user.password_reset_requested"  # noqa: S105 (action name, not a secret)
    USER_PASSWORD_RESET = "user.password_reset"  # noqa: S105 (action name, not a secret)
    USER_PASSWORD_CHANGED = "user.password_changed"  # noqa: S105 (action name, not a secret)
    ORG_CREATED = "organization.created"
    ORG_UPDATED = "organization.updated"
    ORG_MEMBER_UPDATED = "organization.member_updated"
    ORG_MEMBER_REMOVED = "organization.member_removed"
    INVITATION_CREATED = "invitation.created"
    INVITATION_REVOKED = "invitation.revoked"
    INVITATION_ACCEPTED = "invitation.accepted"
    WORKSPACE_CREATED = "workspace.created"
    WORKSPACE_UPDATED = "workspace.updated"
    WORKSPACE_MEMBER_ADDED = "workspace.member_added"
    WORKSPACE_MEMBER_UPDATED = "workspace.member_updated"
    WORKSPACE_MEMBER_REMOVED = "workspace.member_removed"


def _client_ip(request: HttpRequest | None) -> str | None:
    if request is None:
        return None
    # X-Forwarded-For is client-controlled except for the entries appended by
    # our own proxies. With N trusted proxies, the client IP is the Nth entry
    # from the right. With 0 (default) the header is ignored entirely.
    proxies = settings.TRUSTED_PROXY_COUNT
    forwarded = [p.strip() for p in request.META.get("HTTP_X_FORWARDED_FOR", "").split(",") if p.strip()]
    if proxies > 0 and len(forwarded) >= proxies:
        return forwarded[-proxies]
    return request.META.get("REMOTE_ADDR") or None


def record(
    action: str,
    *,
    actor: Any = None,
    request: HttpRequest | None = None,
    organization_id: uuid.UUID | None = None,
    workspace_id: uuid.UUID | None = None,
    target: Any = None,
    target_type: str = "",
    target_id: str = "",
    metadata: dict[str, Any] | None = None,
) -> AuditLog | None:
    """Write an audit entry. Never raises: auditing must not break the action itself."""
    if actor is None and request is not None and getattr(request, "user", None) is not None:
        actor = request.user if request.user.is_authenticated else None
    if target is not None:
        target_type = target_type or target._meta.label_lower
        target_id = target_id or str(target.pk)
    try:
        return AuditLog.objects.create(
            organization_id=organization_id,
            workspace_id=workspace_id,
            actor=actor,
            actor_email=getattr(actor, "email", "") or "",
            action=action,
            target_type=target_type,
            target_id=target_id,
            metadata=metadata or {},
            ip_address=_client_ip(request),
            user_agent=(request.META.get("HTTP_USER_AGENT", "")[:512] if request else ""),
            request_id=get_request_id() if request else "",
        )
    except Exception:  # pragma: no cover - defensive
        logger.exception("Failed to write audit log action=%s", action)
        return None
