# ResolveAI — Architecture

_Last updated: 2026-11-09 (through Phase 4)_

## 1. System overview

```
                    ┌───────────────────────── Browser ─────────────────────────┐
                    │  Dashboard (Next.js)                 Website widget (P2)  │
                    └──────────────┬───────────────────────────────┬────────────┘
                                   │ same-origin /api/* + cookie   │ public widget API
                                   ▼                               ▼ (scoped tokens, P2)
                    ┌──────────────────────────┐      ┌──────────────────────────┐
                    │ Next.js server            │      │  Ingress / Nginx / ALB   │
                    │  - SSR/static pages       │      └────────────┬─────────────┘
                    │  - proxy.ts (optimistic)  │                   │
                    │  - rewrites /api → Django │───────────────────┤
                    └──────────────────────────┘                   ▼
                                         ┌────────────────────────────────────────┐
                                         │ Django (ASGI: uvicorn)                  │
                                         │  DRF REST API  /api/v1/...              │
                                         │  Channels WebSockets (P2)               │
                                         │  apps/* domain modules (modular monolith)│
                                         └──────┬──────────────┬──────────────┬────┘
                                                │              │              │
                                     ┌──────────▼───┐   ┌──────▼─────┐   ┌────▼───────────┐
                                     │ PostgreSQL 17│   │   Redis 7  │   │ Celery workers │
                                     │ + pgvector   │   │ cache/chan/│   │ + beat         │
                                     │              │   │ broker     │   │ (email, AI, RAG)│
                                     └──────────────┘   └────────────┘   └────────────────┘
```

* **Modular monolith** (ADR-0001). One Django project, one database, domain apps with
  explicit boundaries. Split into services only when a module has a proven, independent
  scaling or deployment need.
* **Next.js is a thin BFF**: it serves the UI and proxies `/api/*` to Django so the session
  cookie is first-party (ADR-0003). It holds no secrets and makes no authorization decisions.
* **Async work** (email now; ingestion, embeddings, AI execution, webhooks later) runs in Celery.
  Emails are enqueued with `transaction.on_commit`, so rolled-back operations never send mail.

## 2. Repository layout

```
backend/
  config/            settings (base/dev/test/prod), urls, asgi (Channels), celery
  common/            cross-cutting: base models, RBAC registry, errors, pagination,
                     request IDs, CSRF helpers, email task, OpenAPI extensions
  apps/
    accounts/        custom User, registration, login, verification, password flows
    organizations/   Organization, OrganizationMembership, Invitation (+ services)
    workspaces/      Workspace, WorkspaceMembership, WorkspaceOwnedModel base, Tag, Team
    tenancy/         access resolution + DRF mixins (NOT a Django app; no models)
    audit/           append-only AuditLog + `record()` service
    customers/       Customer, CustomerIdentity (visitor tokens), CustomerNote
    conversations/   Conversation, Message, Attachment, Event, Assignment, ReadState
    widget/          public visitor API, visitor auth, WidgetSettings, widget CORS
    realtime/        Channels consumers, WS routing, publish helpers (no models)
    knowledge/       KnowledgeSource/Chunk (pgvector), extraction, chunking, embeddings, retrieval
    ai_agents/       AIAgent, AIExecution, ToolExecution, LLM providers, LangGraph pipeline
    workflows/       Workflow, WorkflowExecution, declarative engine, beat scan
    integrations/    Integration, IntegrationDelivery (signed webhooks, Slack)
    billing/         Plan, Subscription, UsageLedger, Invoice, WebhookEvent, payment providers
    analytics/       tenant-scoped metrics (no models)
  tests/             pytest suite (API, permissions, isolation, models, infra)
frontend/
  src/app/           App Router routes: public, (auth), /app/*
  src/components/    ui/ (shadcn, Base UI), auth/, app/ (shell, team, settings)
  src/lib/           api client, types, zod schemas, TanStack Query hooks
  src/proxy.ts       optimistic auth redirect for /app/*
widget/              embeddable chat widget: vanilla TS + Shadow DOM, esbuild -> dist/widget.js
infrastructure/      deployment assets (Phase 5)
docs/                architecture, API schema, ADRs, status
```

Messages live in `conversations` (no separate `messaging` app); see ADR-0007.

## 3. Backend layering

| Layer | Responsibility | Rules |
|---|---|---|
| `views.py` | HTTP: parse, call service, serialize | No business logic. Declare `permission_by_action`. |
| `serializers.py` | Input validation, output shape | Restrict FK querysets to the caller's tenant. |
| `services.py` | Business operations, transactions, audit | `@transaction.atomic` for multi-row writes. Raise `ServiceError`/`ConflictError`. |
| `models.py` | Schema, constraints, invariants | DB constraints for anything that must never be violated. |
| `apps/tenancy` | Who may access which tenant | Only place that turns (user, tenant id) into an access decision. |

## 4. Multi-tenancy model

* **Organization** = billing and ownership boundary.
* **Workspace** = support environment and data-isolation boundary (an org has 1..n).
* A **User** can belong to many organizations (`OrganizationMembership`) and to specific
  workspaces (`WorkspaceMembership`). Each membership has a role and `is_active`.
* Every future tenant-owned table inherits `WorkspaceOwnedModel` (`organization` + `workspace`
  FKs; the organization is always derived from the workspace, never from client input).
* Workspace-scoped endpoints live under `/api/v1/workspaces/{workspace_id}/...` (ADR-0002) and
  use `WorkspaceScopedViewMixin`, which resolves access on every request and exposes
  `self.workspace` for queryset filtering.

### Access resolution (`apps/tenancy/access.py`)

```
get_workspace_access(user, workspace_id):
  user active?                                      else → None (404)
  workspace exists and not archived?                else → None (404)
  active OrganizationMembership in its org?         else → None (404)
  effective role = Admin if org role ∈ {owner, admin}
                   else active WorkspaceMembership.role
  role is None?                                     → None (404)
  return WorkspaceAccess(role, permissions)
view checks permission_by_action[action] ∈ permissions   else → 403
```

Unknown or unauthorized tenants return **404** (no existence oracle); authorized members
missing a permission get **403**. Actions absent from `permission_by_action` are **denied by
default**.

## 5. Roles and permissions

Defined once in `backend/common/rbac.py`; the `/auth/me` payload ships the resolved permission
list to the frontend for UI gating only.

| Org role | Key permissions | Workspace access |
|---|---|---|
| Owner | everything incl. ownership transfer, billing manage, delete | implicit Admin in all workspaces |
| Admin | settings, members, invitations, workspaces, audit log | implicit Admin in all workspaces |
| Billing Admin | view org, view members, billing view/manage | explicit memberships only |
| Member | view org | explicit memberships only |

| Workspace role | Adds |
|---|---|
| Viewer | read workspace, members, conversations, customers, agents, knowledge, workflows, analytics |
| Agent | + reply, assign, manage customers |
| Supervisor | + manage conversations, knowledge, workflows |
| Admin | + workspace settings, members, AI agents, integrations |

Invariants (enforced in services, tested): only Owners can grant/modify Owner; an org always
keeps ≥1 active Owner (row-locked check); Admins can assign Admin/Member/Billing Admin.

## 6. Authentication

* Django sessions in an **HttpOnly, SameSite=Lax** cookie (`resolveai_session`), DB-backed with
  cache reads (`cached_db`). Session key rotates on login (fixation protection).
* CSRF: Django CSRF cookie (`resolveai_csrftoken`, readable by the SPA) echoed in `X-CSRFToken`.
  Enforced for **all** unsafe requests, including anonymous login/register (login-CSRF).
* Passwords: Argon2id, Django validators (min 10 chars, common/numeric/similarity checks).
* Email verification: stateless signed token bound to user id **and** current email, 48h.
* Password reset: Django token generator (single-use, 1h, invalidated by password change).
  Password changes invalidate all other sessions via the session auth hash.
* Rate limits (DRF throttles on Redis): `auth` 10/min, `auth_sensitive` 5/hour (reset requests,
  verification resend), anon 60/min, user 600/min.

## 7. API conventions

* Versioned under `/api/v1/`, trailing slashes, UUIDs in paths (`<uuid:...>` converters, so
  malformed IDs 404 at routing).
* Pagination: `{count, next, previous, results}`; `?page=`, `?page_size=` (max 100).
* Search/order via `?search=` / `?ordering=` where declared.
* Errors always use one envelope:
  `{"error": {"code", "message", "details", "request_id"}}`. Unhandled exceptions are logged
  with the request ID and returned as a generic `server_error`.
* Every response carries `X-Request-ID` (accepted from a trusted caller if well-formed).
* OpenAPI: `/api/v1/schema/`, Swagger UI `/api/v1/docs/` (disabled by default in prod);
  exported to `docs/api/openapi.yaml`.

### Phase 1 endpoints

| Method | Path | Permission |
|---|---|---|
| GET | `/health/` | public |
| GET | `/auth/csrf/` | public |
| POST | `/auth/register/`, `/auth/login/`, `/auth/logout/` | public (CSRF) |
| GET/PATCH | `/auth/me/` | authenticated |
| POST | `/auth/verify-email/`, `/auth/verify-email/resend/` | public / authenticated |
| POST | `/auth/password-reset/`, `/auth/password-reset/confirm/`, `/auth/password/change/` | public / authenticated |
| GET/POST | `/organizations/` | authenticated |
| GET/PATCH | `/organizations/{org}/` | org.view / org.update |
| GET | `/organizations/{org}/members/` | org.members.view |
| PATCH/DELETE | `/organizations/{org}/members/{membership}/` | org.members.manage |
| GET/POST | `/organizations/{org}/invitations/` | org.members.view / manage |
| POST | `/organizations/{org}/invitations/{id}/revoke/` | org.members.manage |
| POST | `/organizations/{org}/workspaces/` | org.workspaces.create |
| GET | `/organizations/{org}/audit-logs/` | org.audit.view |
| POST | `/invitations/preview/`, `/invitations/accept/` | public (token) / authenticated |
| GET | `/workspaces/` | authenticated (accessible only) |
| GET/PATCH | `/workspaces/{ws}/` | workspace.view / workspace.update |
| GET/POST | `/workspaces/{ws}/members/` | workspace.members.view / manage |
| PATCH/DELETE | `/workspaces/{ws}/members/{membership}/` | workspace.members.manage |

### Phase 2 endpoints (workspace-scoped: `/api/v1/workspaces/{ws}/...`)

| Method | Path | Permission |
|---|---|---|
| GET/POST | `customers/` (`?q=&type=identified|anonymous&tag=`) | customers.view / customers.manage |
| GET/PATCH/DELETE | `customers/{id}/` | customers.view / customers.manage / workspace.update |
| GET/POST | `customers/{id}/notes/`; DELETE `customer-notes/{id}/` | customers.view / manage (author or admin deletes) |
| GET | `customers/{id}/timeline/` | customers.view |
| GET/POST | `conversations/` (`?status=&assignee=me|unassigned|{id}&team=&tag=&customer=&priority=&unread=&q=`) | conversations.view / reply |
| GET/PATCH | `conversations/{id}/` (status, priority, subject, tag_ids) | conversations.view / reply |
| POST | `conversations/{id}/assign/` (assignee_id, team_id; null clears) | conversations.assign |
| GET/POST | `conversations/{id}/messages/` (cursor-paginated; multipart `files`) | conversations.view / reply |
| GET | `conversations/{id}/events/`, `conversations/counts/` | conversations.view |
| POST | `conversations/{id}/read/` | conversations.view |
| GET | `assignees/`, `attachments/{id}/download/` | conversations.view |
| GET/POST/PATCH/DELETE | `tags/`, `teams/` | workspace.view / conversations.manage, workspace.members.manage |
| GET/PATCH | `widget-settings/` | workspace.view / workspace.update |

**Public widget API** (`/api/v1/widget/...`, bearer session token, its own CORS, no cookies):
`POST session/`, `GET/POST conversations/`, `GET/POST conversations/{id}/messages/`,
`POST identify/`, `GET attachments/{id}/`. See ADR-0006.

**WebSockets**: `/ws/workspaces/{ws}/` (session cookie + dashboard Origin; ID-only events) and
`/ws/widget/` (auth frame `{type: "auth", token}`; the visitor's own replies + typing). See ADR-0005.

### Phase 3–4 endpoints

Workspace-scoped (`/api/v1/workspaces/{ws}/…`):

| Path | Purpose | Permission |
|---|---|---|
| `knowledge/sources/` (CRUD, multipart file upload), `…/{id}/reindex/`, `…/{id}/chunks/` | Knowledge Hub | knowledge.view / knowledge.manage |
| `knowledge/search/` | Retrieval testing | knowledge.view |
| `ai-agents/` (CRUD), `…/{id}/deploy/`, `…/undeploy/`, `…/playground/`, `…/executions/`, `ai-agents/providers/` | AI Agent Studio | ai_agents.view / ai_agents.manage |
| `conversations/{id}/ai/{summarize\|take-over\|resume}/` | AI controls in the inbox | conversations.reply |
| `ai-executions/?conversation=` | AI activity for a conversation | conversations.view |
| `workflows/` (CRUD), `…/{id}/executions/`, `workflows/schema/` | Automation | workflows.view / workflows.manage |
| `integrations/` (CRUD), `…/{id}/test/`, `…/rotate-secret/`, `…/deliveries/` | Webhooks & Slack | integrations.manage |
| `analytics/?start=&end=` | Workspace metrics | analytics.view |

Organization-scoped: `organizations/{org}/billing/` (overview + usage), `…/billing/checkout/`, `…/billing/invoices/`
(org.billing.view/manage), `organizations/{org}/analytics/` (roll-up, org.analytics.view: owners/admins).
Public: `billing/plans/`, `billing/webhooks/{stripe|razorpay|mock}/` (signature-verified, idempotent).

### AI reply lifecycle (brief §4F, ADR-0008)

```
customer message ─▶ message.created (after commit) ─▶ ai_reply_task (Celery)
  ─▶ deployed agent? ai_state ACTIVE? newest customer message? AI quota left?
  ─▶ LangGraph: check_request → retrieve (pgvector, workspace-filtered) → generate (provider, ≤2 tool rounds)
                → validate (leak/empty/refusal) → decide (needs_human / confidence)
  ─▶ _deliver(): SELECT … FOR UPDATE conversation → re-check ai_state → post AI reply or handoff message
  ─▶ AIExecution + ToolExecutions + UsageLedger rows (idempotent) → realtime events → widget + inbox
```

### Domain events (ADR-0010)
`conversations.services` emits `conversation.created`, `message.created`, `conversation.status_changed`,
`conversation.assigned` after commit. Subscribers: AI (`ai_agents`), workflows, integrations — each only
enqueues Celery tasks. Workflow-caused events are ignored by workflows (no loops).

## 8. Frontend architecture

* Next.js 16 App Router with `cacheComponents`. Public pages prerender statically; the
  dashboard is client-rendered and fetches via TanStack Query.
* `src/lib/api.ts` is the only HTTP entry point: same-origin, CSRF handling, error envelope →
  `ApiError` with `fieldErrors` mapped onto react-hook-form fields.
* `AppProvider` loads `/auth/me`, tracks the current workspace (persisted in localStorage),
  and exposes `canWorkspace()` / `canOrg()` for UX gating. A 401/403 from `/me` clears the
  session and redirects to `/login`.
* UI kit: shadcn/ui (`base-nova` style on Base UI primitives — compose with `render`, not
  `asChild`), Tailwind v4, Lucide icons, zod + react-hook-form.
* Route components that read `useSearchParams`/`useParams`/`usePathname` sit behind `<Suspense>`
  (required with `cacheComponents`). Dashboard pages set `export const instant = false` because
  they render only after the client-side session check.
* Inbox (`/app/inbox`, `/app/inbox/[conversationId]`): three panes (views, list, thread with a
  customer sidebar); filters live in the URL. `RealtimeProvider` holds one socket per workspace and
  invalidates `["ws", workspaceId, ...]` query keys on events; typing state is kept in context.
* Customers (`/app/customers`, `/app/customers/[customerId]`), Settings -> Inbox (tags, teams) and
  Settings -> Widget (install snippet, branding, allowed origins).

* Phase 3–4 pages: AI Agents (list, new, detail with Settings / Playground with decision trace /
  Activity), Knowledge Hub (list with live ingestion status, add-source dialog, retrieval tester, source
  detail), Automation (workflow builder driven by `workflows/schema/`), Analytics (KPI tiles, validated
  3-series SVG trend chart with crosshair tooltip + table view, agent table), Integrations, Billing (plan,
  usage meters, INR/USD plans, invoices) and public `/pricing`. The inbox shows AI state with
  Take over / Resume / Summarize controls and distinct AI/automation message styling.

## 8b. Website widget (`widget/`)

* Vanilla TypeScript with no runtime dependencies, bundled by esbuild into one IIFE
  (`dist/widget.js`, ~17 KB / 6 KB gzipped). Mounted in a Shadow DOM. All text is inserted via
  `textContent` (no HTML rendering path exists), and the brand colour is validated as `#rrggbb`.
* Config comes from the script tag (`data-workspace-id`, `data-api-url`); `window.ResolveAI`
  exposes `open/close/identify/shutdown`.
* Talks to the public widget API with `credentials: "omit"`, refreshes the session on 401, and
  uses a WebSocket with backoff and the auth-frame handshake.
* Dev: `npm run dev` serves `demo/index.html?ws=<public_id>` on :3002.

## 9. Observability (current)

* Request ID middleware + log filter; every log line has `request_id=`.
* `/api/v1/health/` checks DB and cache (503 when degraded) for load balancer probes.
* Phase 5 adds structured JSON logs, Sentry, metrics and tracing.

## Production runtime (Phase 5)

One backend image runs three roles: uvicorn (ASGI, HTTP + WebSockets), the Celery worker and Celery beat. An ingress (Nginx, or an ALB) routes `/api`, `/ws` and `/static` to Django and everything else to the Next.js standalone server, so the browser sees a single origin.

The `migrate` one-shot runs `check --deploy` first and refuses unsafe config. Probes: `/api/v1/health/live/` checks nothing beyond the process; `/api/v1/health/ready/` checks the database, cache and broker. Logs are JSON lines carrying `request_id`. Sentry is optional and scrubs PII. The database runs either psycopg pooling or persistent connections, with a server-side statement timeout.

Details: [ADR-0012](../decisions/0012-production-runtime.md), [DEPLOYMENT.md](../operations/DEPLOYMENT.md) and [MONITORING.md](../operations/MONITORING.md). Append-only ledgers are covered in [ADR-0011](../decisions/0011-database-enforced-append-only.md).
