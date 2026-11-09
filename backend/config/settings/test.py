"""Test settings: fast hashing, in-memory cache/channels/email, eager Celery.

PostgreSQL is still required (pgvector, JSONB, constraints behave like prod).
"""

from .base import *  # noqa: F403
from .base import REST_FRAMEWORK

DEBUG = False
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
SESSION_ENGINE = "django.contrib.sessions.backends.db"
CHANNEL_LAYERS = {"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}}
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True
CELERY_BROKER_URL = "memory://"
CELERY_RESULT_BACKEND = "cache+memory://"

# Throttling is exercised explicitly in dedicated tests; keep rates high otherwise.
REST_FRAMEWORK = {
    **REST_FRAMEWORK,
    "DEFAULT_THROTTLE_RATES": {
        "anon": "10000/min",
        "user": "10000/min",
        "auth": "10000/min",
        "auth_sensitive": "10000/min",
        "widget_session": "10000/min",
        "widget_write": "10000/min",
        "widget_read": "10000/min",
        "ai_playground": "10000/min",
    },
}
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}

# Deterministic origins regardless of any developer .env.
FRONTEND_URL = "http://localhost:3000"
CSRF_TRUSTED_ORIGINS = [FRONTEND_URL]
CORS_ALLOWED_ORIGINS = [FRONTEND_URL]
WIDGET_SESSION_TTL_SECONDS = 3600

# Deterministic, offline AI and billing in tests.
ANTHROPIC_API_KEY = ""
OPENAI_API_KEY = ""
AI_ALLOW_MOCK_FALLBACK = True
EMBEDDING_PROVIDER = "hashing"
STRIPE_SECRET_KEY = "sk_test_dummy"  # noqa: S105 (test dummy)
STRIPE_WEBHOOK_SECRET = "whsec_test_stripe"  # noqa: S105 (test dummy)
RAZORPAY_KEY_ID = "rzp_test_dummy"
RAZORPAY_KEY_SECRET = "rzp_secret_dummy"  # noqa: S105 (test dummy)
RAZORPAY_WEBHOOK_SECRET = "rzp_whsec_test"  # noqa: S105 (test dummy)
BILLING_ALLOW_MOCK = True
FIELD_ENCRYPTION_KEY = ""
