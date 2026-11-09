"""Authentication for website visitors (ADR-0006).

Two credentials:
* **visitor token** — long-lived random secret kept in the visitor's browser
  (localStorage). Only its SHA-256 is stored (CustomerIdentity). It is exchanged
  for a session token and is never sent on ordinary API calls.
* **session token** — short-lived (default 1h) signed token used as a Bearer
  credential on every widget API call. It binds workspace + customer + identity,
  so it can only ever read that visitor's data in that workspace.

Every request re-validates: signature/expiry, identity still exists and still
maps to the same customer and workspace, the workspace is active, the widget is
enabled, and the request Origin is allowed for the workspace.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.core import signing
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed, PermissionDenied
from rest_framework.permissions import BasePermission
from rest_framework.request import Request
from rest_framework.throttling import SimpleRateThrottle

from apps.customers.models import Customer, CustomerIdentity
from apps.widget.models import WidgetSettings
from apps.workspaces.models import Workspace

TOKEN_SALT = "resolveai.widget.session.v1"  # noqa: S105 (signing namespace, not a secret)


@dataclass(frozen=True)
class WidgetSession:
    workspace: Workspace
    settings: WidgetSettings
    customer: Customer
    identity: CustomerIdentity


def get_widget_settings(workspace: Workspace) -> WidgetSettings:
    obj, _ = WidgetSettings.objects.get_or_create(workspace=workspace)
    return obj


def issue_session_token(identity: CustomerIdentity) -> str:
    return signing.dumps(
        {"w": str(identity.workspace_id), "c": str(identity.customer_id), "i": str(identity.id)}, salt=TOKEN_SALT
    )


def resolve_session_token(token: str, origin: str | None) -> WidgetSession:
    """Validate a session token. Raises AuthenticationFailed / PermissionDenied."""
    try:
        payload: dict[str, Any] = signing.loads(token, salt=TOKEN_SALT, max_age=settings.WIDGET_SESSION_TTL_SECONDS)
        identity_id = uuid.UUID(payload["i"])
    except (signing.BadSignature, KeyError, TypeError, ValueError) as exc:
        raise AuthenticationFailed("Widget session is invalid or expired.", code="widget_session_invalid") from exc

    identity = (
        CustomerIdentity.objects.select_related("customer", "workspace", "workspace__organization")
        .filter(id=identity_id)
        .first()
    )
    if (
        identity is None
        or str(identity.workspace_id) != payload.get("w")
        or str(identity.customer_id) != payload.get("c")
        or identity.customer.workspace_id != identity.workspace_id
        or identity.workspace.archived_at is not None
    ):
        raise AuthenticationFailed("Widget session is invalid or expired.", code="widget_session_invalid")

    widget_settings = get_widget_settings(identity.workspace)
    if not widget_settings.enabled:
        raise PermissionDenied("The chat widget is not available.", code="widget_unavailable")
    if not widget_settings.origin_allowed(origin):
        raise PermissionDenied("This website is not allowed to use this chat widget.", code="origin_not_allowed")
    return WidgetSession(identity.workspace, widget_settings, identity.customer, identity)


class WidgetTokenAuthentication(BaseAuthentication):
    keyword = "Bearer"

    def authenticate(self, request: Request) -> tuple[AnonymousUser, WidgetSession] | None:
        header = request.headers.get("Authorization", "")
        if not header.startswith(f"{self.keyword} "):
            return None
        token = header[len(self.keyword) + 1 :].strip()
        if not token:
            return None
        return AnonymousUser(), resolve_session_token(token, request.headers.get("Origin"))

    def authenticate_header(self, request: Request) -> str:
        return self.keyword


class IsWidgetVisitor(BasePermission):
    def has_permission(self, request: Request, view: Any) -> bool:
        return isinstance(request.auth, WidgetSession)


class VisitorRateThrottle(SimpleRateThrottle):
    """Rate limit per visitor (customer) when authenticated, else per client IP."""

    def get_cache_key(self, request: Request, view: Any) -> str:
        session = request.auth if isinstance(request.auth, WidgetSession) else None
        ident = f"c:{session.customer.id}" if session else f"ip:{self.get_ident(request)}"
        return self.cache_format % {"scope": self.scope, "ident": ident}


class WidgetSessionThrottle(VisitorRateThrottle):
    scope = "widget_session"


class WidgetWriteThrottle(VisitorRateThrottle):
    scope = "widget_write"


class WidgetReadThrottle(VisitorRateThrottle):
    scope = "widget_read"
