"""Logging, error tracking and request telemetry.

* JsonFormatter — one JSON object per line (CloudWatch / Loki / Datadog friendly),
  always carrying request_id.
* RequestLogMiddleware — one structured access log per request with the resolved
  route template (not the raw path, so IDs don't explode metric cardinality),
  status, duration and the authenticated user id.
* init_sentry — error tracking with PII scrubbing; a no-op unless SENTRY_DSN is set.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from django.http import HttpRequest, HttpResponse

from common.middleware import get_request_id

access_logger = logging.getLogger("resolveai.access")

_RESERVED = set(vars(logging.LogRecord("", 0, "", 0, "", None, None))) | {"message", "asctime", "request_id"}
SCRUBBED = "[scrubbed]"
SENSITIVE_KEYS = {
    "password",
    "new_password",
    "current_password",
    "token",
    "session_token",
    "visitor_token",
    "authorization",
    "cookie",
    "set-cookie",
    "x-csrftoken",
    "stripe-signature",
    "x-razorpay-signature",
    "api_key",
    "secret",
}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "request_id": getattr(record, "request_id", get_request_id()),
        }
        for key, value in record.__dict__.items():
            if key not in _RESERVED and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


class RequestLogMiddleware:
    """Structured access log. Skips health probes to keep logs signal-rich."""

    SKIP_PREFIXES = ("/api/v1/health/",)

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        started = time.monotonic()
        response = self.get_response(request)
        if request.path.startswith(self.SKIP_PREFIXES):
            return response
        match = getattr(request, "resolver_match", None)
        user = getattr(request, "user", None)
        access_logger.info(
            "request",
            extra={
                "method": request.method,
                "route": f"/{match.route}" if match and match.route else request.path[:100],
                "status": response.status_code,
                "duration_ms": round((time.monotonic() - started) * 1000, 1),
                "user_id": str(user.pk) if user is not None and user.is_authenticated else None,
            },
        )
        return response


class SecurityHeadersMiddleware:
    """Defensive headers for API responses (JSON never needs to render or be framed)."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        response = self.get_response(request)
        if request.path.startswith("/api/"):
            response.setdefault("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'; sandbox")
            # The widget API is called from customer sites; everything else is same-site only.
            corp = "cross-origin" if request.path.startswith("/api/v1/widget/") else "same-site"
            response.setdefault("Cross-Origin-Resource-Policy", corp)
            # Authenticated data must never be stored by shared caches or the browser's disk cache.
            response.setdefault("Cache-Control", "no-store")
        response.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=(), payment=()")
        response.setdefault("X-Content-Type-Options", "nosniff")
        return response


def _scrub(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: SCRUBBED if str(k).lower() in SENSITIVE_KEYS else _scrub(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_scrub(v) for v in value]
    return value


def scrub_event(event: dict[str, Any], hint: dict[str, Any] | None = None) -> dict[str, Any]:
    """Sentry before_send: drop bodies/cookies/auth headers; never ship customer content."""
    request = event.get("request") or {}
    request.pop("data", None)
    request.pop("cookies", None)
    if "headers" in request:
        request["headers"] = _scrub(request["headers"])
    if "query_string" in request:
        request["query_string"] = SCRUBBED
    event["request"] = request
    if "extra" in event:
        event["extra"] = _scrub(event["extra"])
    return event


def init_sentry(dsn: str, environment: str, release: str, traces_sample_rate: float) -> bool:
    if not dsn:
        return False
    import sentry_sdk
    from sentry_sdk.integrations.celery import CeleryIntegration
    from sentry_sdk.integrations.django import DjangoIntegration

    sentry_sdk.init(
        dsn=dsn,
        environment=environment,
        release=release or None,
        integrations=[DjangoIntegration(), CeleryIntegration()],
        send_default_pii=False,
        traces_sample_rate=traces_sample_rate,
        before_send=scrub_event,
    )
    return True
