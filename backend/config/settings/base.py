"""Base Django settings shared by every environment.

Environment-specific modules (dev/test/prod) import from here and override.
All secrets and deployment-specific values come from environment variables.
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import environ
from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent.parent
REPO_ROOT = BASE_DIR.parent

env = environ.Env()
# Load a repo-level .env for local development if present. Real deployments
# inject variables via the environment / secrets manager instead.
for candidate in (REPO_ROOT / ".env", BASE_DIR / ".env"):
    if candidate.exists():
        environ.Env.read_env(str(candidate), overwrite=False)

SECRET_KEY = env("DJANGO_SECRET_KEY")
DEBUG = env.bool("DJANGO_DEBUG", default=False)
ALLOWED_HOSTS: list[str] = env.list("DJANGO_ALLOWED_HOSTS", default=["localhost", "127.0.0.1"])
FRONTEND_URL: str = env("FRONTEND_URL", default="http://localhost:3000").rstrip("/")

# -----------------------------------------------------------------------------
# Applications
# -----------------------------------------------------------------------------
DJANGO_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.postgres",
]
THIRD_PARTY_APPS = [
    "corsheaders",
    "rest_framework",
    "drf_spectacular",
    "channels",
]
LOCAL_APPS = [
    "common",
    "apps.accounts",
    "apps.organizations",
    "apps.workspaces",
    "apps.audit",
    "apps.customers",
    "apps.conversations",
    "apps.widget",
    "apps.knowledge",
    "apps.ai_agents",
    "apps.billing",
    "apps.workflows",
    "apps.integrations",
]
INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "common.middleware.RequestIDMiddleware",
    "common.observability.RequestLogMiddleware",
]
MIDDLEWARE.insert(1, "common.observability.SecurityHeadersMiddleware")
# Must run before CorsMiddleware so widget preflights never get credentialed CORS headers.
MIDDLEWARE.insert(
    MIDDLEWARE.index("corsheaders.middleware.CorsMiddleware"), "apps.widget.middleware.WidgetCorsMiddleware"
)

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

# -----------------------------------------------------------------------------
# Database
# -----------------------------------------------------------------------------
if env("DATABASE_URL", default=""):
    DATABASES = {"default": env.db("DATABASE_URL")}
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": env("POSTGRES_DB", default="resolveai"),
            "USER": env("POSTGRES_USER", default="resolveai"),
            "PASSWORD": env("POSTGRES_PASSWORD", default=""),
            "HOST": env("POSTGRES_HOST", default="localhost"),
            "PORT": env("POSTGRES_PORT", default="5433"),
        }
    }
# Connection strategy. DB_POOL=true uses psycopg's in-process pool (Django 5.1+),
# which requires CONN_MAX_AGE=0; otherwise persistent connections with health checks.
# Behind PgBouncer (transaction mode) set DB_POOL=false and DB_CONN_MAX_AGE=0.
DB_POOL = env.bool("DB_POOL", default=False)
if DB_POOL:
    DATABASES["default"]["CONN_MAX_AGE"] = 0
    DATABASES["default"].setdefault("OPTIONS", {})["pool"] = {
        "min_size": env.int("DB_POOL_MIN_SIZE", default=2),
        "max_size": env.int("DB_POOL_MAX_SIZE", default=10),
        "timeout": env.int("DB_POOL_TIMEOUT_SECONDS", default=10),
    }
else:
    DATABASES["default"]["CONN_MAX_AGE"] = env.int("DB_CONN_MAX_AGE", default=60)
    DATABASES["default"]["CONN_HEALTH_CHECKS"] = True
# Kill runaway queries server-side rather than letting them pin a worker.
DB_STATEMENT_TIMEOUT_MS = env.int("DB_STATEMENT_TIMEOUT_MS", default=30000)
if DB_STATEMENT_TIMEOUT_MS:
    DATABASES["default"].setdefault("OPTIONS", {})["options"] = f"-c statement_timeout={DB_STATEMENT_TIMEOUT_MS}"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# -----------------------------------------------------------------------------
# Auth
# -----------------------------------------------------------------------------
AUTH_USER_MODEL = "accounts.User"
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 10}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
]
PASSWORD_RESET_TIMEOUT = 60 * 60  # 1 hour
LOGIN_LOCKOUT_THRESHOLD = env.int("LOGIN_LOCKOUT_THRESHOLD", default=10)
LOGIN_LOCKOUT_WINDOW_SECONDS = env.int("LOGIN_LOCKOUT_WINDOW_SECONDS", default=15 * 60)
EMAIL_VERIFICATION_MAX_AGE_SECONDS = env.int("EMAIL_VERIFICATION_MAX_AGE_SECONDS", default=60 * 60 * 48)
INVITATION_EXPIRY = timedelta(days=env.int("INVITATION_EXPIRY_DAYS", default=7))

# Sessions: HttpOnly cookie, server-side store (DB-backed, cached reads).
SECURE_COOKIES = env.bool("SECURE_COOKIES", default=False)
SESSION_ENGINE = "django.contrib.sessions.backends.cached_db"
SESSION_COOKIE_NAME = "resolveai_session"
SESSION_COOKIE_AGE = env.int("SESSION_COOKIE_AGE_SECONDS", default=60 * 60 * 24 * 14)
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_SECURE = SECURE_COOKIES
CSRF_COOKIE_NAME = "resolveai_csrftoken"
CSRF_COOKIE_HTTPONLY = False  # SPA reads it and echoes it in X-CSRFToken
CSRF_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SECURE = SECURE_COOKIES
CSRF_TRUSTED_ORIGINS: list[str] = env.list("CSRF_TRUSTED_ORIGINS", default=[FRONTEND_URL])

# CORS: only the dashboard origin may make credentialed calls. The public
# widget API (Phase 2) gets its own per-workspace origin validation.
CORS_ALLOWED_ORIGINS: list[str] = env.list("CORS_ALLOWED_ORIGINS", default=[FRONTEND_URL])
CORS_ALLOW_CREDENTIALS = True
# Dashboard API only. The public widget API has its own CORS handling
# (apps.widget.middleware.WidgetCorsMiddleware): any configured origin, no cookies.
CORS_URLS_REGEX = r"^/api/(?!v1/widget/).*$"

# -----------------------------------------------------------------------------
# I18N
# -----------------------------------------------------------------------------
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

# -----------------------------------------------------------------------------
# Static / media
# -----------------------------------------------------------------------------
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "media/"  # never routed publicly; files are served via authorized endpoints only
MEDIA_ROOT = BASE_DIR / "media"

# Private object storage. With AWS_STORAGE_BUCKET_NAME set, files go to S3 (or any
# S3-compatible store via AWS_S3_ENDPOINT_URL) with private ACLs; otherwise local disk.
AWS_STORAGE_BUCKET_NAME = env("AWS_STORAGE_BUCKET_NAME", default="")
if AWS_STORAGE_BUCKET_NAME:
    STORAGES = {
        "default": {
            "BACKEND": "storages.backends.s3.S3Storage",
            "OPTIONS": {
                "bucket_name": AWS_STORAGE_BUCKET_NAME,
                "endpoint_url": env("AWS_S3_ENDPOINT_URL", default="") or None,
                "region_name": env("AWS_S3_REGION_NAME", default="") or None,
                "default_acl": "private",
                "querystring_auth": True,
                "file_overwrite": False,
            },
        },
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }
else:
    STORAGES = {
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }

# Attachments
ATTACHMENT_MAX_BYTES = env.int("ATTACHMENT_MAX_BYTES", default=10 * 1024 * 1024)
ATTACHMENT_MAX_FILES = 5
DATA_UPLOAD_MAX_MEMORY_SIZE = 2 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 2 * 1024 * 1024

# -----------------------------------------------------------------------------
# AI (Phase 3)
# -----------------------------------------------------------------------------
ANTHROPIC_API_KEY = env("ANTHROPIC_API_KEY", default="")
OPENAI_API_KEY = env("OPENAI_API_KEY", default="")
AI_REQUEST_TIMEOUT_SECONDS = env.float("AI_REQUEST_TIMEOUT_SECONDS", default=60.0)
# Without an API key, use the offline mock provider instead of failing (dev/test only).
AI_ALLOW_MOCK_FALLBACK = env.bool("AI_ALLOW_MOCK_FALLBACK", default=True)
# "auto" = OpenAI embeddings when OPENAI_API_KEY is set, else the local hashing embedder.
EMBEDDING_PROVIDER = env("EMBEDDING_PROVIDER", default="auto")
KNOWLEDGE_MAX_FILE_BYTES = env.int("KNOWLEDGE_MAX_FILE_BYTES", default=20 * 1024 * 1024)

# -----------------------------------------------------------------------------
# Billing & integrations (Phase 4)
# -----------------------------------------------------------------------------
STRIPE_SECRET_KEY = env("STRIPE_SECRET_KEY", default="")
STRIPE_WEBHOOK_SECRET = env("STRIPE_WEBHOOK_SECRET", default="")
RAZORPAY_KEY_ID = env("RAZORPAY_KEY_ID", default="")
RAZORPAY_KEY_SECRET = env("RAZORPAY_KEY_SECRET", default="")
RAZORPAY_WEBHOOK_SECRET = env("RAZORPAY_WEBHOOK_SECRET", default="")
# Development-only mock payment provider (signed events through the real webhook pipeline).
BILLING_ALLOW_MOCK = env.bool("BILLING_ALLOW_MOCK", default=True)
# Fernet key for secrets stored in the DB (integration URLs). Required in production.
FIELD_ENCRYPTION_KEY = env("FIELD_ENCRYPTION_KEY", default="")

CELERY_BEAT_SCHEDULE = {
    "workflows-scan-unanswered": {"task": "apps.workflows.tasks.scan_unanswered_task", "schedule": 60.0},
}

# Website widget
WIDGET_SESSION_TTL_SECONDS = env.int("WIDGET_SESSION_TTL_SECONDS", default=60 * 60)

# -----------------------------------------------------------------------------
# Cache / Redis / Channels / Celery
# -----------------------------------------------------------------------------
REDIS_URL = env("REDIS_URL", default="redis://localhost:6380/0")
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": REDIS_URL,
        "KEY_PREFIX": "resolveai",
    }
}
CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {
            "hosts": [
                {
                    "address": env("CHANNEL_LAYER_REDIS_URL", default="redis://localhost:6380/3"),
                    # channels_redis blocks on BZPOPMIN for 5s per receive. redis-py >= 8
                    # defaults socket_timeout to 5s, so reads race and time out, killing
                    # every WebSocket consumer. Keep the read timeout well above 5s.
                    "socket_timeout": 30,
                    "socket_connect_timeout": 5,
                    "health_check_interval": 30,
                }
            ],
        },
    }
}
CELERY_BROKER_URL = env("CELERY_BROKER_URL", default="redis://localhost:6380/1")
CELERY_RESULT_BACKEND = env("CELERY_RESULT_BACKEND", default="redis://localhost:6380/2")
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_ACKS_LATE = True
CELERY_WORKER_PREFETCH_MULTIPLIER = 1
CELERY_TASK_TIME_LIMIT = 60 * 10
CELERY_TASK_SOFT_TIME_LIMIT = 60 * 9
CELERY_TIMEZONE = TIME_ZONE
# Run tasks inline (no worker) — handy for single-process local debugging only.
CELERY_TASK_ALWAYS_EAGER = env.bool("CELERY_TASK_ALWAYS_EAGER", default=False)

# -----------------------------------------------------------------------------
# Email
# -----------------------------------------------------------------------------
# NOTIFICATION_BACKEND: "console" (print emails, default) or "smtp".
NOTIFICATION_BACKEND = env("NOTIFICATION_BACKEND", default="console").strip().lower()
if NOTIFICATION_BACKEND not in {"console", "smtp"}:
    raise ImproperlyConfigured("NOTIFICATION_BACKEND must be 'console' or 'smtp'.")
EMAIL_BACKEND = {
    "console": "django.core.mail.backends.console.EmailBackend",
    "smtp": "django.core.mail.backends.smtp.EmailBackend",
}[NOTIFICATION_BACKEND]
EMAIL_HOST = env("SMTP_HOST", default="")
EMAIL_PORT = env.int("SMTP_PORT", default=587)
EMAIL_HOST_USER = env("SMTP_USERNAME", default="")
EMAIL_HOST_PASSWORD = env("SMTP_PASSWORD", default="")
if env("SMTP_PASSWORD_VAULT_REF", default=""):
    # Secret-manager references aren't resolved by the app (yet). Inject the secret into
    # SMTP_PASSWORD at deploy time instead (e.g. ECS task secrets / Kubernetes secrets).
    raise ImproperlyConfigured("SMTP_PASSWORD_VAULT_REF is not supported yet; set SMTP_PASSWORD instead.")
# Port 465 = implicit TLS (SMTPS); anything else (587) = STARTTLS.
EMAIL_USE_SSL = EMAIL_PORT == 465
EMAIL_USE_TLS = not EMAIL_USE_SSL
EMAIL_TIMEOUT = env.int("SMTP_TIMEOUT_SECONDS", default=15)
SMTP_FROM = env("SMTP_FROM", default="no-reply@resolveai.local")
DEFAULT_FROM_EMAIL = f"{env('SMTP_FROM_NAME', default='ResolveAI')} <{SMTP_FROM}>"
SERVER_EMAIL = DEFAULT_FROM_EMAIL
if NOTIFICATION_BACKEND == "smtp" and not (EMAIL_HOST and EMAIL_HOST_USER):
    raise ImproperlyConfigured("NOTIFICATION_BACKEND=smtp requires SMTP_HOST and SMTP_USERNAME.")

# -----------------------------------------------------------------------------
# Django REST Framework
# -----------------------------------------------------------------------------
# Number of reverse proxies (load balancer, ingress) in front of Django that
# append to X-Forwarded-For. Used for audit IPs and rate-limit identity.
TRUSTED_PROXY_COUNT = env.int("TRUSTED_PROXY_COUNT", default=0)

REST_FRAMEWORK = {
    "NUM_PROXIES": TRUSTED_PROXY_COUNT or None,
    "DEFAULT_AUTHENTICATION_CLASSES": ["common.authentication.CsrfEnforcedSessionAuthentication"],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_PAGINATION_CLASS": "common.pagination.StandardPagination",
    "PAGE_SIZE": 25,
    "DEFAULT_FILTER_BACKENDS": [
        "rest_framework.filters.SearchFilter",
        "rest_framework.filters.OrderingFilter",
    ],
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "EXCEPTION_HANDLER": "common.exceptions.api_exception_handler",
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.UserRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "anon": "60/min",
        "user": "600/min",
        "auth": "10/min",
        "auth_sensitive": "5/hour",
        "widget_session": "30/min",
        "widget_write": "30/min",
        "widget_read": "120/min",
        "ai_playground": "30/min",
    },
}

SPECTACULAR_SETTINGS = {
    "TITLE": "ResolveAI API",
    "DESCRIPTION": "Multi-tenant AI customer support platform API.",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "SCHEMA_PATH_PREFIX": r"/api/v1",
    "COMPONENT_SPLIT_REQUEST": True,
    "ENUM_NAME_OVERRIDES": {
        "OrganizationRoleEnum": "apps.organizations.models.OrganizationRole",
        "WorkspaceRoleEnum": "apps.workspaces.models.WorkspaceRole",
        "ConversationStatusEnum": "apps.conversations.models.ConversationStatus",
        "ConversationPriorityEnum": "apps.conversations.models.ConversationPriority",
        "InvitationStatusEnum": "apps.organizations.models.InvitationStatus",
        "ActorTypeEnum": "apps.conversations.models.ActorType",
        "MessageKindEnum": "apps.conversations.models.MessageKind",
        "ChannelEnum": "apps.conversations.models.Channel",
        "KnowledgeSourceKindEnum": "apps.knowledge.models.SourceKind",
        "IntegrationKindEnum": "apps.integrations.models.IntegrationKind",
        "AIProviderEnum": "apps.ai_agents.models.Provider",
        "AIEffortEnum": "apps.ai_agents.models.Effort",
    },
}

# -----------------------------------------------------------------------------
# Logging — request-correlated; LOG_FORMAT=json emits one JSON object per line.
# -----------------------------------------------------------------------------
LOG_LEVEL = env("LOG_LEVEL", default="INFO")
LOG_FORMAT = env("LOG_FORMAT", default="text")
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {"request_id": {"()": "common.middleware.RequestIDLogFilter"}},
    "formatters": {
        "default": {
            "format": "%(asctime)s level=%(levelname)s logger=%(name)s request_id=%(request_id)s %(message)s",
        },
        "json": {"()": "common.observability.JsonFormatter"},
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "json" if LOG_FORMAT == "json" else "default",
            "filters": ["request_id"],
        },
    },
    "root": {"handlers": ["console"], "level": LOG_LEVEL},
    "loggers": {
        "django.db.backends": {"level": "WARNING"},
        # Access logs are noisy in local dev; enable with LOG_ACCESS=true.
        "resolveai.access": {"level": "INFO" if env.bool("LOG_ACCESS", default=False) else "WARNING"},
    },
}

# -----------------------------------------------------------------------------
# Error tracking (Sentry). Disabled unless SENTRY_DSN is set; PII is scrubbed.
# -----------------------------------------------------------------------------
SENTRY_DSN = env("SENTRY_DSN", default="")
SENTRY_ENVIRONMENT = env("SENTRY_ENVIRONMENT", default=env("DJANGO_ENV", default="dev"))
SENTRY_TRACES_SAMPLE_RATE = env.float("SENTRY_TRACES_SAMPLE_RATE", default=0.0)
APP_RELEASE = env("APP_RELEASE", default="")
if SENTRY_DSN:
    from common.observability import init_sentry

    init_sentry(SENTRY_DSN, SENTRY_ENVIRONMENT, APP_RELEASE, SENTRY_TRACES_SAMPLE_RATE)

# -----------------------------------------------------------------------------
# Misc
# -----------------------------------------------------------------------------
# Obscure the admin path in production via env (e.g. "ops-7f3a/").
ADMIN_URL = env("DJANGO_ADMIN_URL", default="admin/")
# OpenAPI schema + Swagger UI. Disable (or put behind auth) in production.
API_DOCS_ENABLED = env.bool("API_DOCS_ENABLED", default=True)
