# ADR-0012: Production runtime, observability and ingress

* Status: Accepted · Date: 2026-11-09

## Decision

* **One backend image, three roles.** `uvicorn` (ASGI: HTTP and WebSockets), the Celery `worker`, and the Celery `beat` all run the same `prod` image with different commands, so they can never drift apart. Uvicorn runs `--workers $WEB_CONCURRENCY` with `--proxy-headers` and `--forwarded-allow-ips` limited to the proxy. Gunicorn's `UvicornWorker` is deprecated upstream and adds no value here.
* **Ingress routes by path.** `/api/*`, `/ws/*` and `/static/*` go to Django; everything else goes to Next.js. The browser sees one origin, so the session cookie stays first-party (ADR-0003). The Next.js `/api` rewrite remains only as a dev and fallback path. The Django admin is not routed publicly.
* **Fail fast on configuration.** Custom deploy checks (`common/checks.py`, `resolveai.E001–E008`) run in the `migrate` one-shot before anything starts. Advisory items are warnings (`W101–W109`).
* **Probes.** Liveness has no dependencies. Readiness checks the database, cache and broker.
* **Logs.** JSON lines carry a request id. The access log records the route template rather than the raw path, to keep cardinality bounded. Celery failure and retry signals are logged without task arguments.
* **Errors.** Sentry is opt-in through `SENTRY_DSN`, with `send_default_pii=False` and a custom scrubber.
* **Database.** Two connection modes: psycopg's in-process pool (`DB_POOL=true`, which needs `CONN_MAX_AGE=0`), or persistent connections with health checks. Behind PgBouncer or RDS Proxy, use neither. A server-side `statement_timeout` (30s by default) stops runaway queries from pinning workers; migrations disable it.
* **Static files.** WhiteNoise with compressed, hashed manifest storage, served from the backend (production only). Media stays on private S3 (production settings no longer override it — a Phase 4 bug fixed here).
* **Frontend.**
  * Next.js runs as a `standalone` server: a small image with no full `node_modules`.
  * A static CSP: `script-src 'self' 'unsafe-inline'`, `frame-ancestors 'none'`, `object-src 'none'`, a `connect-src` limited to self and the WebSocket origin, plus COOP `same-origin`.
  * A nonce-based CSP was rejected for now. It forces dynamic rendering of every page, which defeats Partial Prerendering, and `next-themes` injects an inline script. Revisit once nonce support works with Cache Components.
* **API headers.** Every `/api/*` response carries `Content-Security-Policy: default-src 'none'; frame-ancestors 'none'; sandbox`, `Cache-Control: no-store`, `Cross-Origin-Resource-Policy` (`same-site`, or `cross-origin` for the widget API), `Permissions-Policy` and `nosniff`.
* **Account lockout.** Per-account lockout complements the per-IP throttles: 10 failures in 15 minutes locks that email for the rest of the window, and the password isn't checked while the lock is active. The bounded lock window limits how long an attacker can lock a victim out, and password reset is never blocked.

## Consequences

* \+ The same artifacts run on a single host (`docker-compose.prod.yml`) and on ECS/Fargate.
* \+ Unsafe deploys are refused automatically, and operators get structured, correlated logs.
* − `'unsafe-inline'` scripts weaken the CSP against injected inline scripts. React's escaping and the absence of `dangerouslySetInnerHTML` on user content are the primary XSS defences.
* − Per-account lockout can be abused to lock a known email out temporarily. This is accepted, given the short window and the reset path.
