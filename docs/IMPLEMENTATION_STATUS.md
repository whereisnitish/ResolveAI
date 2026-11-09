# Implementation status

_Last updated: 2026-11-09, end of Phase 5 (production readiness)._

Legend: **Not started** · **In progress** · **Implemented** · **Tested** · **Production ready**
("Tested" means automated tests cover the behaviour and pass. "Production ready" additionally requires real provider keys, a real environment and your approval to deploy. Nothing has been deployed.)

| Module | Status | Notes |
|---|---|---|
| Foundation: accounts, orgs, workspaces, RBAC, tenancy, audit | Tested | Phase 1 |
| Customers, conversations, inbox, real-time, widget | Tested | Phase 2 |
| **LLM provider abstraction** (Anthropic, OpenAI, Mock) | Tested | Real providers tested against fake SDK clients; live calls need API keys |
| **AI agent management + Agent Studio UI** | Tested | Config, deploy (one per workspace), handoff rules |
| **LangGraph orchestration** (12-step lifecycle) | Tested | Tools, safety validation, structured output |
| **Knowledge ingestion** (PDF/TXT/MD/URL/FAQ/text) | Tested | Celery, SSRF-safe crawling, re-index, delete |
| **Embeddings + RAG retrieval** (pgvector HNSW) | Tested | OpenAI or local hashing embedder; retrieval tester UI |
| **AI execution logs** | Tested | Steps, sources, tokens, latency, tool calls |
| **Playground** | Tested | Dry run with decision trace |
| **Human handoff / AI pause–resume** | Tested | Critical test #7, mutation-checked |
| **AI conversation summaries** | Tested | Inbox “Summarize” |
| **Workflow automation** | Tested | 4 triggers, 8 actions, conditions, beat-based escalation |
| **Analytics** (workspace + org roll-up) | Tested | KPIs, daily series, agent performance; validated SVG chart |
| **Team management** | Tested | Members, roles, invitations, seats enforced by plan |
| **Integrations** (signed webhooks, Slack) | Tested | Encrypted URLs, retries, delivery log; live delivery to httpbin verified |
| **Usage tracking** (append-only ledger) | Tested | AI runs, tokens, conversations, embeddings; seats/storage live |
| **Billing foundations** (plans, trial, subscriptions, invoices) | Tested | Stripe/Razorpay webhooks + checkout request shape; mock provider in dev |
| Pricing page | Implemented | `/pricing`, INR/USD toggle |
| **Production config** (deploy checks, JSON logs, Sentry, probes, DB pool, statement timeout, WhiteNoise) | Tested | `check --deploy` blocks unsafe config (E001–E008) |
| **Security hardening** (DB-enforced append-only audit/usage, per-account lockout, API + dashboard CSP/headers, error pages) | Tested | ADR-0011, ADR-0012 |
| **N+1 guards** (query count flat from 2→12 rows on list endpoints) | Tested | conversations, customers, tags, audit logs |
| **Deployment** (prod Dockerfiles, Next standalone, Nginx ingress, `docker-compose.prod.yml`) | Implemented | Images built and smoke-tested locally; not deployed |
| **Backups** (backup / restore / verify scripts) | Tested | Verified restore against the dev DB |
| **Browser E2E** (Playwright) | Tested | Full journey 6/6, two consecutive runs |
| **CI pipeline** (GitHub Actions) | Implemented | Not yet run on GitHub (no remote); steps run locally |
| Row-Level Security | Deferred | ADR-0011: app-layer isolation + tests; upgrade path documented |

## Critical security tests (from the master brief)

| # | Test | Status |
|---|---|---|
| 1 | Org A user cannot access Org B data | ✅ every endpoint through Phase 4 |
| 2 | Unauthorized workspace by guessing UUID | ✅ |
| 3 | Inactive members cannot access workspace data | ✅ |
| 4 | Widget tokens cannot access another workspace | ✅ mutation-checked |
| 5 | Anonymous visitors cannot call privileged dashboard APIs | ✅ |
| 6 | Duplicate webhooks not processed twice | ✅ `test_billing.py` + live, mutation-checked |
| 7 | AI cannot reply after human takeover (unless configured) | ✅ `test_ai_agents.py` + live, mutation-checked |

All seven critical tests now pass.

## Latest results (2026-11-09, Phase 5)

* **Backend:** `pytest`: **277 passed**, coverage **92%**. `ruff` is clean, the OpenAPI schema is valid (115 operations), there are no pending migrations, and `pip-audit` reports no known vulnerabilities.
* **Frontend:** `vitest`: **36 passed**. `eslint` and `tsc` are clean, `next build` succeeds (standalone output), and `npm audit --omit=dev` finds 0 vulnerabilities.
* **Browser E2E** (Playwright, Chromium): **6/6**, run twice. The journey is signup → text knowledge indexed → agent created and deployed → widget origin allowed → a visitor on the demo site asks a question → the AI answers from knowledge (no handoff) → the teammate sees it in the inbox and replies → the visitor receives the reply live → the AI is paused. It also checks that a signed-out user is redirected to login.
* **Images:** backend 643 MB, frontend 315 MB, widget 93 MB. The backend image refuses placeholder config (`check --deploy` exit 1). With valid config, against Postgres and Redis, readiness reports database, cache and broker ok, the DB pool is active, static files are served and API security headers are present. The frontend image serves the CSP, COOP and 404 pages.
* **Backups:** dump of 46 table-data entries → `verify-backup.sh` restored exact row counts on 8 critical tables, plus 2 append-only triggers, the HNSW index and 41 migrations. `restore.sh` refused to overwrite an existing database.
* **Widget:** 16 tests pass (unchanged in Phases 3–4).
* **Live end-to-end** (Django + Redis + Next + widget socket, eager Celery): **36/36 checks**. These cover ingestion (FAQ + PDF), SSRF rejection, retrieval, agent creation (Claude default), playground, an AI answer delivered to the visitor over WebSocket, takeover silencing the AI, handoff, summary, workflow tagging, the integration SSRF block plus a signed delivery to httpbin.org, analytics, trial metering, mock checkout → active plan, INR invoice, duplicate and forged webhooks, and all new pages rendering.

## Defaults and decisions to review

* Anthropic default model `claude-opus-5-5` at medium effort. OpenAI default `gpt-5.5`. Both are configurable per agent.
* The server-side refusal fallback (`fallbacks: "default"`) is enabled on supported Claude models. A refusal still results in a handoff if the fallback also declines.
* Without keys: offline mock LLM plus local hashing embeddings (development only). Production settings disable the mock fallback.

## Known gaps / follow-ups

* **Not deployed anywhere.** The Phase 5 artifacts are ready. Deploying needs your approval plus real infrastructure and keys (see [DEPLOYMENT.md](operations/DEPLOYMENT.md)).
* The CI workflow has not run on GitHub yet because the project has no git history or remote. Its steps were run locally.
* The dashboard CSP needs `'unsafe-inline'` for scripts (ADR-0012). Nonce-based CSP is a follow-up.
* WhiteNoise under ASGI logs a sync-iterator warning when serving static files. It is harmless; a CDN in front of `/static/` avoids it.
* Still to do: MFA/SSO, a transactional outbox, a tenant erasure command (must use `allow_purge()`), and RLS.

* No live LLM, Stripe or Razorpay calls were made (no keys in this environment). Providers are tested against fake clients and HTTP mocks.
* Hashing embeddings are lexical. Set `OPENAI_API_KEY` (or add a Voyage/Cohere embedder) and re-index for semantic retrieval.
* Billing: no customer portal, proration, GST/tax invoices, dunning emails or cancellation flow yet. Razorpay plan ids must be configured per plan.
* Website crawling ingests a single URL (no sitemap or multi-page crawl yet).
* Native provider tool calling (instead of JSON tool requests); streaming AI replies.
* The domain event bus is in-process; consider a transactional outbox for guaranteed delivery.
* Verified visitor identity (HMAC) and visitor attachments, carried over from Phase 2.
