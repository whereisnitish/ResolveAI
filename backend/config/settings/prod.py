"""Production settings. Every security-relevant flag is on by default."""

from .base import *  # noqa: F403
from .base import env

DEBUG = False

SECURE_COOKIES = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = env.bool("SECURE_SSL_REDIRECT", default=True)
SECURE_HSTS_SECONDS = env.int("SECURE_HSTS_SECONDS", default=60 * 60 * 24 * 365)
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"
X_FRAME_OPTIONS = "DENY"

# Keep the base media backend (S3 when AWS_STORAGE_BUCKET_NAME is set); serve hashed,
# pre-compressed static assets from the app via WhiteNoise (CDN-cacheable forever).
STORAGES = {
    **STORAGES,
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}
# WhiteNoise serves collected static files (admin) straight after SecurityMiddleware.
MIDDLEWARE.insert(
    MIDDLEWARE.index("django.middleware.security.SecurityMiddleware") + 1, "whitenoise.middleware.WhiteNoiseMiddleware"
)
API_DOCS_ENABLED = env.bool("API_DOCS_ENABLED", default=False)

# No silent fallbacks in production: missing provider keys must surface as errors/handoffs.
AI_ALLOW_MOCK_FALLBACK = env.bool("AI_ALLOW_MOCK_FALLBACK", default=False)
BILLING_ALLOW_MOCK = False
FIELD_ENCRYPTION_KEY = env("FIELD_ENCRYPTION_KEY")  # required
# JSON logs in production (base LOGGING honours LOG_FORMAT).
LOGGING["handlers"]["console"]["formatter"] = "json" if env("LOG_FORMAT", default="json") == "json" else "default"
LOGGING["loggers"]["resolveai.access"]["level"] = "INFO" if env.bool("LOG_ACCESS", default=True) else "WARNING"
