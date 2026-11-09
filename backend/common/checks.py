"""Deployment checks: `python manage.py check --deploy` fails fast on unsafe production config.

Errors (E) block a deploy; warnings (W) are surfaced for review.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

from django.conf import settings
from django.core.checks import Error, Tags, Warning, register


@register(Tags.security, deploy=True)
def resolveai_deploy_checks(app_configs: Any = None, **kwargs: Any) -> list[Any]:
    issues: list[Any] = []

    def err(code: str, msg: str, hint: str = "") -> None:
        issues.append(Error(msg, hint=hint or None, id=f"resolveai.E{code}"))

    def warn(code: str, msg: str, hint: str = "") -> None:
        issues.append(Warning(msg, hint=hint or None, id=f"resolveai.W{code}"))

    if settings.DEBUG:
        err("001", "DEBUG must be False in production.")
    if len(settings.SECRET_KEY) < 50 or "change-me" in settings.SECRET_KEY:
        err("002", "DJANGO_SECRET_KEY is weak or a placeholder.", "Generate 64+ random characters.")
    if not settings.ALLOWED_HOSTS or "*" in settings.ALLOWED_HOSTS:
        err("003", "DJANGO_ALLOWED_HOSTS must list your domains explicitly.")
    for name in ("FRONTEND_URL",):
        if urlsplit(getattr(settings, name)).scheme != "https":
            err("004", f"{name} must be an https:// URL in production.")
    if any(urlsplit(o).scheme != "https" for o in settings.CSRF_TRUSTED_ORIGINS):
        err("005", "CSRF_TRUSTED_ORIGINS must only contain https:// origins.")
    if settings.AI_ALLOW_MOCK_FALLBACK:
        err("006", "AI_ALLOW_MOCK_FALLBACK must be False in production (no fake AI answers).")
    if settings.BILLING_ALLOW_MOCK:
        err("007", "BILLING_ALLOW_MOCK must be False in production.")
    try:
        from cryptography.fernet import Fernet

        Fernet(settings.FIELD_ENCRYPTION_KEY)
    except Exception:
        err("008", "FIELD_ENCRYPTION_KEY is missing or not a valid Fernet key.", "Fernet.generate_key()")

    if not (settings.ANTHROPIC_API_KEY or settings.OPENAI_API_KEY):
        warn("101", "No LLM provider key configured: AI agents will hand every conversation to humans.")
    if settings.EMBEDDING_PROVIDER in ("auto", "hashing") and not settings.OPENAI_API_KEY:
        warn("102", "Knowledge retrieval uses the local hashing embedder (lexical). Configure OPENAI_API_KEY.")
    if settings.NOTIFICATION_BACKEND != "smtp":
        warn("103", "NOTIFICATION_BACKEND is not smtp: verification/reset emails will not be delivered.")
    if settings.NOTIFICATION_BACKEND == "smtp" and not settings.EMAIL_HOST_PASSWORD:
        warn("104", "SMTP_PASSWORD is empty.")
    if not getattr(settings, "AWS_STORAGE_BUCKET_NAME", ""):
        warn("105", "No S3 bucket configured: uploads go to local disk (needs a persistent, backed-up volume).")
    if not getattr(settings, "SENTRY_DSN", ""):
        warn("106", "SENTRY_DSN not set: errors are only visible in logs.")
    if settings.STRIPE_SECRET_KEY and not settings.STRIPE_WEBHOOK_SECRET:
        warn("107", "STRIPE_SECRET_KEY is set without STRIPE_WEBHOOK_SECRET: Stripe checkout stays disabled.")
    if settings.STRIPE_SECRET_KEY.startswith(("sk_test_", "rk_test_")):
        warn("108", "Stripe is in TEST mode.")
    if settings.TRUSTED_PROXY_COUNT == 0:
        warn("109", "TRUSTED_PROXY_COUNT=0: client IPs in audit logs/rate limits will be the proxy's IP.")
    return issues
