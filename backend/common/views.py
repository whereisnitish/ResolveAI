from __future__ import annotations

import logging

from django.core.cache import cache
from django.db import connection
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

logger = logging.getLogger(__name__)


def _check_database() -> str:
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")
    return "ok"


def _check_cache() -> str:
    cache.set("health:ping", "1", timeout=5)
    return "ok" if cache.get("health:ping") == "1" else "error"


def _check_broker() -> str:
    """The Celery broker (Redis). Skipped in eager mode (tests / single-process dev)."""
    from django.conf import settings

    if settings.CELERY_TASK_ALWAYS_EAGER:
        return "ok"
    import redis

    client = redis.Redis.from_url(settings.CELERY_BROKER_URL, socket_connect_timeout=2, socket_timeout=2)
    try:
        return "ok" if client.ping() else "error"
    finally:
        client.close()


READINESS_CHECKS = {"database": _check_database, "cache": _check_cache, "broker": _check_broker}

_health_schema = extend_schema(
    responses={200: inline_serializer("Health", {"status": serializers.CharField(), "checks": serializers.DictField()})}
)


class _ProbeView(APIView):
    permission_classes = [AllowAny]
    authentication_classes: list = []
    throttle_classes: list = []


class LivenessView(_ProbeView):
    """Liveness: the process is up and serving. No dependencies — a DB outage must not
    make the orchestrator restart every healthy container."""

    @_health_schema
    def get(self, request: Request) -> Response:
        return Response({"status": "ok", "checks": {}})


class HealthView(_ProbeView):
    """Readiness: dependencies reachable. Reports status only, never internal details."""

    @_health_schema
    def get(self, request: Request) -> Response:
        checks: dict[str, str] = {}
        for name, check in READINESS_CHECKS.items():
            try:
                checks[name] = check()
            except Exception:
                logger.exception("health_check_failed component=%s", name)
                checks[name] = "error"
        healthy = all(v == "ok" for v in checks.values())
        return Response({"status": "ok" if healthy else "degraded", "checks": checks}, status=200 if healthy else 503)
