# syntax=docker/dockerfile:1
# Targets:  dev  — local development (dev/test tooling, source bind-mounted)
#           prod — production runtime (no dev deps, collected static, non-root)
FROM python:3.13-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq5 curl \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 1000 app

COPY requirements/ requirements/

# ---------------------------------------------------------------- dev
FROM base AS dev
RUN pip install -r requirements/dev.txt
COPY . .
RUN chown -R app:app /app
USER app
EXPOSE 8000
CMD ["uvicorn", "config.asgi:application", "--host", "0.0.0.0", "--port", "8000"]

# ---------------------------------------------------------------- prod
FROM base AS prod
RUN pip install -r requirements/base.txt
COPY --chown=app:app . .
# collectstatic only needs importable settings; these throwaway values never reach runtime.
RUN DJANGO_ENV=prod \
    DJANGO_SECRET_KEY=build-only-not-a-secret \
    FIELD_ENCRYPTION_KEY=MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA= \
    python manage.py collectstatic --noinput \
    && rm -rf tests media && mkdir -p media && chown -R app:app /app
USER app

ARG APP_RELEASE=""
ENV DJANGO_ENV=prod \
    APP_RELEASE=${APP_RELEASE} \
    WEB_CONCURRENCY=2

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
    CMD curl -fsS http://localhost:8000/api/v1/health/live/ || exit 1
# ASGI (HTTP + WebSockets). TLS terminates at the load balancer / Nginx; uvicorn trusts
# X-Forwarded-* only from FORWARDED_ALLOW_IPS (set it to your proxy subnet).
CMD ["sh", "-c", "exec uvicorn config.asgi:application --host 0.0.0.0 --port 8000 --workers ${WEB_CONCURRENCY} --proxy-headers --forwarded-allow-ips \"${FORWARDED_ALLOW_IPS:-127.0.0.1}\" --timeout-graceful-shutdown 25 --no-server-header --no-access-log"]
