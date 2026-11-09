# Deployment

ResolveAI ships as three images plus an ingress:

| Image | Built from | Runs |
|---|---|---|
| `resolveai-backend` | `backend/Dockerfile` target `prod` | API + WebSockets (`uvicorn`, ASGI); the **same image** runs the Celery `worker` and `beat` |
| `resolveai-frontend` | `frontend/Dockerfile` target `prod` | Next.js standalone server (dashboard + marketing pages) |
| `resolveai-widget` | `widget/Dockerfile` | static `widget.js` (put a CDN in front) |
| ingress | `infrastructure/nginx/nginx.conf` or an ALB | `/api/*`, `/ws/*`, `/static/*` → backend; everything else → frontend |

Nothing is deployed automatically. CI (`.github/workflows/ci.yml`) builds and tests the images; promoting them to an environment is a manual, approved step.

## Before every production deploy

1. CI is green on the commit: lint, all backend tests (including the 7 critical security tests), frontend and widget tests, dependency audits, the image build and the Playwright E2E journey.
2. Run `python manage.py check --deploy --fail-level ERROR` with the production environment. The `migrate` one-shot does this automatically and **refuses to start** on `DEBUG`, placeholder secrets, `http://` origins, mock AI or billing fallbacks, or an invalid `FIELD_ENCRYPTION_KEY`. Review the warnings (`resolveai.W1xx`) too.
3. Take a fresh backup, or confirm the managed snapshot is recent (see [BACKUPS.md](BACKUPS.md)).
4. Read the migration list (`python manage.py showmigrations`). Migrations are additive by convention. Anything destructive needs a two-phase deploy: ship code that stops using the column, then drop it in a later release.

## Single host (staging or small installs): `docker-compose.prod.yml`

```bash
cp .env.prod.example .env.prod        # fill every CHANGE_ME — never commit it
export APP_RELEASE=$(git rev-parse --short HEAD)
docker compose -f docker-compose.prod.yml --env-file .env.prod build
docker compose -f docker-compose.prod.yml --env-file .env.prod up -d
docker compose -f docker-compose.prod.yml logs -f migrate backend
```

Startup order: `db`, `redis` → `migrate` (deploy check, then migrations) → `backend`, `worker`, `beat` → `frontend` → `nginx`.

The compose nginx listens on HTTP port 80. For TLS, either put a TLS-terminating load balancer in front (keep `TRUSTED_PROXY_COUNT` in step with the number of proxies), or add a `listen 443 ssl` server block with mounted certificates.

## AWS reference architecture

```
Route 53 ─► CloudFront ─┬─► S3 (widget.js, long-cache)       ◄── resolveai-widget build output
                        └─► ALB (HTTPS, ACM cert, WAF)
                              ├─ /api/*, /ws/*, /static/* ─► ECS service "backend"   (Fargate, ≥2 tasks, multi-AZ)
                              └─ /*                       ─► ECS service "frontend"  (Fargate, ≥2 tasks)
ECS service "worker" (Fargate, autoscale on queue depth)   ECS service "beat" (exactly 1 task)
RDS PostgreSQL 17 + pgvector (Multi-AZ, PITR 14–35 days, encrypted, RDS Proxy optional)
ElastiCache Redis 7 (cluster mode off, Multi-AZ, encryption in transit + at rest)
S3 bucket for uploads (private, SSE-KMS, versioning, Block Public Access)
Secrets Manager / SSM Parameter Store → injected as ECS task environment
CloudWatch Logs (JSON) · Sentry · CloudWatch alarms → SNS/PagerDuty
```

Notes:

* **WebSockets through the ALB.** ALB supports WebSocket upgrades natively. Set the idle timeout to at least 300s. The dashboard reconnects automatically.
* **Exactly one `beat`.** Two beat processes double-fire the "customer waiting" scan. Workflow runs are deduplicated by `dedupe_key`, but the work is wasted.
* **Database extensions.** On RDS, `vector`, `citext` and `pg_trgm` are created by the migrations. The migration role needs `rds_superuser` once, for `CREATE EXTENSION`.
* **Connection budget.** `backend tasks × WEB_CONCURRENCY × DB_POOL_MAX_SIZE + worker tasks × concurrency` must stay below RDS `max_connections`. Use RDS Proxy (with `DB_POOL=false` and `DB_CONN_MAX_AGE=0`) when you scale out past that.
* **Static files.** WhiteNoise serves hashed admin and DRF assets from the backend image (`collectstatic` runs at build time). CloudFront can cache `/static/*` indefinitely.
* **Frontend build-time values.** `NEXT_PUBLIC_*` values and the `/api` rewrite target are baked in at image build time (`--build-arg`). Build one image per environment, or route `/api` and `/ws` at the ALB, which is the recommended setup; then the rewrite is never used.
* **Regions.** For India data residency, use `ap-south-1` (Mumbai). Stripe and Razorpay webhooks must reach `https://<host>/api/v1/billing/webhooks/{stripe,razorpay}/`.

## Environment variables

`.env.example` documents every variable with its development default, and `.env.prod.example` is the production template. The variables `check --deploy` treats as **required in production** are `DJANGO_SECRET_KEY`, `DJANGO_ALLOWED_HOSTS`, `FRONTEND_URL` (https), `CSRF_TRUSTED_ORIGINS` (https) and `FIELD_ENCRYPTION_KEY`. The others it warns about:

* `SENTRY_DSN`
* `SMTP_*`
* `AWS_STORAGE_BUCKET_NAME`
* `ANTHROPIC_API_KEY` / `OPENAI_API_KEY`
* `STRIPE_WEBHOOK_SECRET`
* `TRUSTED_PROXY_COUNT`

`FIELD_ENCRYPTION_KEY` encrypts integration webhook URLs. Store it in Secrets Manager **and** in your break-glass vault: losing it makes those URLs unrecoverable.

## Rollback

* **Code:** redeploy the previous image tag. `APP_RELEASE` makes the running version visible in logs and Sentry.
* **Schema:** migrations are written to be backward compatible with the previous release, so rolling back code needs no schema rollback. Never run `migrate <app> <older>` in production without a fresh backup and an approved plan.
* **Data:** restore into a *new* database with `infrastructure/scripts/restore.sh`, verify it, then repoint `POSTGRES_DB` / `DATABASE_URL`. The script refuses to overwrite an existing database.

## Scaling knobs

| Knob | Where | Default |
|---|---|---|
| API processes per task | `WEB_CONCURRENCY` | 2 |
| Worker concurrency | `CELERY_CONCURRENCY` (compose) / `--concurrency` | 4 |
| DB pool per process | `DB_POOL_MIN_SIZE` / `DB_POOL_MAX_SIZE` | 2 / 10 |
| Statement timeout | `DB_STATEMENT_TIMEOUT_MS` | 30000 |
| Edge rate limits | `infrastructure/nginx/nginx.conf` (`limit_req_zone`) or AWS WAF | 30 r/s per IP for the API, 2 r/s for auth |
| App rate limits | `REST_FRAMEWORK.DEFAULT_THROTTLE_RATES`, `LOGIN_LOCKOUT_*` | see `base.py` |
