# Monitoring, logging and error tracking

## Health probes

| Endpoint | Meaning | Use for |
|---|---|---|
| `GET /api/v1/health/live/` | The process serves HTTP. No dependency checks | Container or ECS liveness (restart on failure) |
| `GET /api/v1/health/ready/` (alias `/api/v1/health/`) | Database, cache and Celery broker reachable. Returns `503` with `{"status":"degraded","checks":{…}}` otherwise | ALB target health and readiness, uptime monitors |
| `GET /nginx-health` | Ingress up | LB → nginx |

Liveness deliberately ignores dependencies. Otherwise a database blip would make the orchestrator restart every healthy API container at once.

## Logs

* In production (`LOG_FORMAT=json`), logs are **one JSON object per line** on stdout, which suits CloudWatch Logs Insights, Loki or Datadog. Every line carries `request_id`, the same value returned in the `X-Request-ID` response header and inside error envelopes. Support can therefore go from a user's error screen to the exact log lines.
* The **access log** (`resolveai.access`, `LOG_ACCESS=true`) writes one line per request:
  * `method`
  * `route`: the URL *template* such as `/api/v1/workspaces/<uuid:workspace_id>/conversations/`, never raw IDs, so metric cardinality stays bounded
  * `status`, `duration_ms`, `user_id`
* **Celery** (`resolveai.tasks`) logs `task_failed` (task name, id, exception type and traceback) and `task_retry`. Task arguments are never logged because they can contain customer content.
* **Never logged:** passwords, tokens, cookies, message bodies, API keys. Webhook and integration secrets are encrypted at rest and redacted.

Useful CloudWatch Logs Insights queries:

```
# p95 latency by route (last 1h)
fields route, duration_ms | filter logger = "resolveai.access"
| stats pct(duration_ms, 95) as p95, count(*) as n by route | sort p95 desc

# 5xx by route
filter logger = "resolveai.access" and status >= 500 | stats count(*) by route, status

# everything for one request
filter request_id = "<id from the X-Request-ID header>"
```

## Error tracking (Sentry)

Sentry is enabled only when `SENTRY_DSN` is set, with the Django and Celery integrations. The release comes from `APP_RELEASE` and the environment from `SENTRY_ENVIRONMENT`. Tracing is sampled with `SENTRY_TRACES_SAMPLE_RATE`; 0.05 is a sensible starting point.

`send_default_pii=False`. The `before_send` scrubber (`common/observability.py`) also:

* drops request bodies and cookies
* redacts auth, CSRF and signature headers
* redacts query strings
* recursively redacts password, token and secret keys in `extra`

This is covered by `tests/test_production_readiness.py`.

## Metrics and alerts (recommended)

| Signal | Source | Alert when |
|---|---|---|
| Readiness failing | ALB unhealthy hosts / uptime check | Any target unhealthy for 2 min |
| API 5xx rate | ALB `HTTPCode_Target_5XX` or access logs | Above 1% of requests for 5 min |
| API latency | access log `duration_ms` p95 | Above 1.5 s for 10 min (excluding AI playground) |
| Celery backlog | Redis `LLEN celery` (queue depth) | Above 500 for 10 min, or growing for 15 min |
| `task_failed` rate | logs | Above 20 per 5 min |
| AI handoff spike | `ai_agents` executions (dashboard Analytics), `ai_failed` events | Handoff rate double the 7-day baseline. Usually a provider outage or missing key |
| Webhook failures | `billing_webhookevent.status = failed` | Any |
| Integration auto-disabled | logs `integration_disabled` | Any (notify the tenant) |
| RDS | CPU, FreeStorageSpace, connections, replica lag | CPU above 80%, storage below 15%, connections above 80% of max |
| Redis | memory, evictions | Evictions above 0 (Redis must run `noeviction` because it is the broker) |
| Backups | `verify-backup.sh` exit code | Non-zero |
| Certificates | ACM | Expiry within 21 days (ACM auto-renews, so alert on failure) |

## Dashboards

The in-app **Analytics** page covers business metrics per workspace: conversations, resolution, AI resolution and handoff rate, first response time, tokens. Operational dashboards (latency, error rate, queue depth, database health) belong in CloudWatch, Grafana or Datadog, built from the signals above.
