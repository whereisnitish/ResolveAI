# ResolveAI

**Your AI workforce for customer support.** A multi-tenant SaaS combining a shared inbox,
website chat widget and AI agents trained on each customer's knowledge — for India and
international markets.

> Status: **Phases 1–4 complete.** Accounts & tenancy, real-time shared inbox and website widget,
> AI agents (Claude/OpenAI via a provider abstraction, LangGraph pipeline, RAG over pgvector,
> human handoff), workflow automation, analytics, integrations, usage metering and billing
> foundations (Stripe + Razorpay). Phase 5 (production readiness) is next.
> See [docs/IMPLEMENTATION_STATUS.md](docs/IMPLEMENTATION_STATUS.md).

## Stack

| Layer | Tech |
|---|---|
| Backend | Python 3.13, Django 6, DRF, drf-spectacular, Channels, Celery |
| Data | PostgreSQL 17 + pgvector, Redis 7 |
| Frontend | Next.js 16 (App Router), TypeScript, Tailwind v4, shadcn/ui (Base UI), TanStack Query, react-hook-form + zod |
| Infra | Docker / Docker Compose, AWS-ready |

## Quick start (local)

Prerequisites: Docker Desktop, Python 3.13, Node 22+.

```bash
cp .env.example .env                       # placeholders only — fine for local dev
docker compose up -d db redis              # Postgres on :5433, Redis on :6380

# Backend
cd backend
py -3.13 -m venv .venv                     # or: python3.13 -m venv .venv
.venv/Scripts/pip install -r requirements/dev.txt   # macOS/Linux: .venv/bin/pip
.venv/Scripts/python manage.py migrate
.venv/Scripts/python -m uvicorn config.asgi:application --port 8000 --reload
# optional, separate terminal (Windows needs --pool=solo):
.venv/Scripts/celery -A config worker --pool=solo -l info
# optional, for scheduled automations ("customer waiting > N minutes"):
.venv/Scripts/celery -A config beat -l info

# Frontend
cd ../frontend
cp .env.example .env.local                 # WS + widget URLs for local dev
npm install
npm run dev                                # http://localhost:3000

# Website widget demo (optional)
cd ../widget
npm install
npm run dev                                # http://localhost:3002/?ws=<workspace public id>
```

The widget's workspace id and install snippet are under **Settings → Widget**. Chat from the
demo page and watch it arrive live in **Inbox**.

Sign up at <http://localhost:3000/signup>. Emails (verification, reset, invites) are printed by the
Celery worker (console backend).

Full stack in Docker instead: `docker compose up --build` (backend :8000, frontend :3000).

> If you serve the dashboard from an origin other than `http://localhost:3000`, add it to
> `CSRF_TRUSTED_ORIGINS` and `FRONTEND_URL` in `.env`.

## Useful commands

```bash
# backend/
.venv/Scripts/python -m pytest                    # tests (needs docker db)
.venv/Scripts/python -m pytest --cov              # with coverage
.venv/Scripts/ruff check . && .venv/Scripts/ruff format --check .
.venv/Scripts/python manage.py spectacular --file ../docs/api/openapi.yaml --validate
.venv/Scripts/python manage.py createsuperuser

# frontend/
npm test            # vitest
npm run lint
npm run typecheck
npm run build

# widget/
npm test && npm run typecheck && npm run build   # -> dist/widget.js
```

> AI and billing run without any keys in development (offline mock LLM, local embeddings, signed
> mock payments). Add `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` / Stripe / Razorpay keys to `.env` to
> use the real services. **Restart Celery workers after pulling new code** — they don't hot-reload.

> Run the backend with `PYTHONUNBUFFERED=1` if you pipe its output to a file, otherwise logs are buffered.

API docs (dev): <http://localhost:8000/api/v1/docs/> · Health: `/api/v1/health/live/` (liveness), `/api/v1/health/ready/` (readiness)

### End-to-end browser tests (Playwright)

```bash
# 1. backend on 8001: eager Celery, mock AI (no keys), dashboard origin 3101
cd backend && DJANGO_ENV=dev CELERY_TASK_ALWAYS_EAGER=true FRONTEND_URL=http://localhost:3101 \
  CSRF_TRUSTED_ORIGINS=http://localhost:3101 CORS_ALLOWED_ORIGINS=http://localhost:3101 \
  .venv/Scripts/python -m uvicorn config.asgi:application --port 8001
# 2. dashboard built against it, served on 3101
cd frontend && BACKEND_INTERNAL_URL=http://localhost:8001 NEXT_PUBLIC_WS_URL=ws://localhost:8001 npm run build && npx next start -p 3101
# 3. widget demo on 3002
cd widget && node build.mjs --serve
# 4. run
cd e2e && npm ci && npx playwright install chromium && npx playwright test
```

### Production

The production images, Nginx ingress, `docker-compose.prod.yml`, backup scripts and runbooks are documented in
[`docs/operations/`](docs/operations/). Start with [DEPLOYMENT.md](docs/operations/DEPLOYMENT.md).
Nothing is deployed automatically.

## Documentation

* [Master build prompt](docs/MASTER_BUILD_PROMPT.md) — the product & engineering specification
* [Architecture](docs/architecture/ARCHITECTURE.md) — system design, tenancy, RBAC, API
* [Database](docs/architecture/DATABASE.md) — schema, constraints, deletion rules
* [Security](docs/architecture/SECURITY.md) — controls and roadmap
* Operations: [Deployment](docs/operations/DEPLOYMENT.md) · [Backups](docs/operations/BACKUPS.md) · [Monitoring](docs/operations/MONITORING.md) · [Runbook](docs/operations/RUNBOOK.md)
* [Decisions (ADRs)](docs/decisions/) · [Conventions](docs/CONVENTIONS.md)
* [OpenAPI schema](docs/api/openapi.yaml)

## Repository layout

```
backend/        Django modular monolith (apps/, common/, config/, tests/)
frontend/       Next.js dashboard + public site
widget/         embeddable website chat widget (vanilla TS, Shadow DOM)
e2e/           Playwright browser tests
infrastructure/ nginx ingress, backup/restore scripts
.github/       CI pipeline
docs/           architecture, API, ADRs, status
```

## Roadmap

1. ✅ Foundation — auth, orgs, workspaces, RBAC, tenant isolation, audit
2. ✅ Core support — customers, conversations, shared inbox, real-time, widget
3. ✅ AI platform — agents, provider abstraction, LangGraph, RAG, handoff
4. ✅ Business — workflows, analytics, team, integrations, usage & billing (Stripe + Razorpay)
5. ✅ Production readiness — hardening, monitoring, backups, deployment artifacts, E2E, CI (RLS deferred, ADR-0011)
