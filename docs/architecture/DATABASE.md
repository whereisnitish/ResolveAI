# ResolveAI — Database design

_PostgreSQL 17 + pgvector. Last updated: 2026-11-09 (through Phase 4)._

## Conventions

* Business entities use **UUID primary keys** (`common.models.BaseModel`): non-enumerable IDs
  in URLs; safe to generate client-side or across shards later.
* `created_at` (indexed) / `updated_at` on every business table.
* Invariants that must never break are **database constraints**, not just application checks.
* Extensions enabled by `common/migrations/0001`: `vector`, `citext`, `pg_trgm`.
* Tenant-owned tables (Phase 2+) inherit `WorkspaceOwnedModel` → `organization_id` +
  `workspace_id` FKs, both indexed via FK indexes; composite indexes start with `workspace_id`.

## Entity relationships (Phase 1)

```
User 1─* OrganizationMembership *─1 Organization 1─* Workspace 1─* WorkspaceMembership *─1 User
                                       │                │
                                       └─* Invitation ──┘ (optional target workspace)
AuditLog (organization_id, workspace_id as plain UUIDs — survives tenant deletion)
```

## Tables

### accounts_user
| Column | Notes |
|---|---|
| id (uuid PK) | |
| email | unique; stored lower-cased; **unique index on `lower(email)`** |
| password | Argon2id hash |
| full_name, is_active, is_staff, is_superuser | |
| email_verified_at | null until verified |
| date_joined, updated_at, last_login | |

### organizations_organization
| Column | Notes |
|---|---|
| id, name, slug (unique) | |
| country | ISO-3166 alpha-2; selects Razorpay (IN) vs Stripe (Phase 4) |
| created_by_id | FK user, SET NULL |

### organizations_organizationmembership
* `UNIQUE(organization_id, user_id)`; index `(user_id, is_active)`.
* `role ∈ {owner, admin, member, billing_admin}`; `is_active` (deactivation keeps history).
* Cascade on org/user delete.

### organizations_invitation
* `token_hash` (SHA-256 of a 256-bit random token, unique) — raw token is never stored.
* `status ∈ {pending, accepted, revoked}`, `expires_at` (expiry computed at read time).
* **Partial unique** `(organization_id, email) WHERE status = 'pending'`.
* **Check**: `workspace_id IS NULL ⇔ workspace_role = ''`.

### workspaces_workspace
* `UNIQUE(organization_id, slug)`.
* **Partial unique** `(organization_id) WHERE is_default` — exactly one default per org.
* `public_id` — random, unique, non-secret identifier for the widget snippet
  (`ws_<22 chars>`); not the primary key, so it can be rotated later.
* `archived_at` — soft archive; archived workspaces are inaccessible.

### workspaces_workspacemembership
* `UNIQUE(workspace_id, user_id)`; index `(user_id, is_active)`.
* `role ∈ {admin, supervisor, agent, viewer}`.

### audit_auditlog (append-only)
* `organization_id`, `workspace_id` stored as **UUIDs without FKs** so logs outlive tenants.
* `actor_id` FK SET NULL + `actor_email` snapshot.
* `action`, `target_type`, `target_id`, `metadata` (JSONB), `ip_address`, `user_agent`, `request_id`.
* Index `(organization_id, created_at DESC)`.
* Model refuses updates and deletes; admin is read-only. (DB-level enforcement — a
  `REVOKE UPDATE, DELETE` for the app role or a trigger — is planned for Phase 5.)

## Phase 2 tables

All inherit `WorkspaceOwnedModel` (`organization_id`, `workspace_id`, UUID PK, timestamps) unless noted.

```
Workspace 1-* Customer 1-* Conversation 1-* Message 1-* Attachment
             |    +-* CustomerIdentity       +-* ConversationEvent (append-only)
             |    +-* CustomerNote           +-* ConversationAssignment (history)
             +-* Tag  (M2M -> Customer, Conversation)   +-* ConversationReadState (per agent)
             +-* Team (M2M -> User)
             +-1 WidgetSettings
```

### workspaces_tag / workspaces_team
* Unique `(workspace_id, lower(name))`. Team-User M2M (members must have workspace access; enforced in the API).

### customers_customer
* `name`, `email` (contact email, **not unique**: unverified claims can collide), `phone`,
  `attributes` (JSONB, at most 50 primitive keys, at most 8 KB), `identified_at` (NULL = anonymous
  visitor), `last_seen_at`, `last_seen_url`, `user_agent`.
* `external_id` is reserved for verified identity: **partial unique** `(workspace_id, external_id) WHERE external_id <> ''`.
* Indexes `(workspace_id, email)`, `(workspace_id, last_seen_at DESC)`.

### customers_customeridentity
* `kind` (`visitor`), `value_hash` = SHA-256 of the visitor token. Unique `(workspace_id, kind, value_hash)`.

### customers_customernote
* `author_id` SET NULL; index `(customer_id, created_at DESC)`.

### conversations_conversation
* `number`: per-workspace sequence from `Workspace.conversation_seq` (row-locked increment);
  unique `(workspace_id, number)`.
* `status` (open/pending/resolved/closed), `priority` (low/normal/high/urgent), `channel`
  (widget/dashboard), `assignee_id` (SET NULL), `team_id` (SET NULL).
* Denormalized for the inbox and maintained only by services: `last_message_at`,
  `last_message_preview`, `last_message_author_type`, `last_customer_message_at`,
  `first_response_at`, `resolved_at`.
* Indexes `(workspace_id, status, last_message_at DESC)`, `(workspace_id, assignee_id, status)`,
  `(workspace_id, team_id, status)`, `(customer_id, last_message_at DESC)`.

### conversations_message
* `kind` (reply = visible to the customer, note = internal), `author_type`, `author_user_id`,
  `author_customer_id`, `body` (at most 10k characters).
* **Check**: `kind = 'note'` implies `author_type IN ('agent', 'system')`.
* Indexes `(conversation_id, created_at)`; **GIN trigram** on `body` for inbox search.

### conversations_attachment
* Private storage key `attachments/<workspace>/<random>.<ext>` (never the user's filename);
  `filename` (sanitized), `content_type` (derived from the validated extension), `size`.

### conversations_conversationevent (append-only)
* `type`, `actor_type`, `actor_user_id`, `data` (JSONB with name snapshots). Index `(conversation_id, created_at)`.

### conversations_conversationassignment
* History rows; **partial unique** `(conversation_id) WHERE ended_at IS NULL`, so at most one open assignment.

### conversations_conversationreadstate (BaseModel)
* Unique `(conversation_id, user_id)`; a conversation is unread when `last_customer_message_at > last_read_at`.

### widget_widgetsettings (BaseModel, one per workspace)
* `enabled`, `allowed_origins` (text[]), `brand_color`, `team_name`, `welcome_message`,
  `launcher_position`, `collect_email`. Only `PUBLIC_FIELDS` are ever sent to visitors.

## Phase 3–4 tables

### conversations_conversation (added)
* `ai_state` (active / paused / handed_off), `ai_handoff_at`, `human_takeover_at`, `ai_summary`, `ai_summary_at`.
* Event types added: `handoff`, `human_takeover`, `ai_resumed`.

### knowledge_knowledgesource (WorkspaceOwned)
* `kind` (file/url/faq/text), `status` (pending/processing/ready/failed), `error`, `enabled`, file fields
  (`file` private key `knowledge/<ws>/<random>.<ext>`, `filename`, `content_type`, `size`), `url`, `faq` (JSONB),
  `text`, `metadata` (JSONB labels for filtering), `content_hash`, `char_count`, `chunk_count`,
  `embedding_model`, `last_indexed_at`. Index `(workspace, status)`.

### knowledge_knowledgechunk (WorkspaceOwned)
* `source` (CASCADE), `position` (unique per source), `content`, **`embedding vector(1536)`**,
  `embedding_model`, `token_count`, `metadata`. **HNSW** index (`vector_cosine_ops`, m=16, ef_construction=64);
  `(workspace, embedding_model)` index. Retrieval always filters workspace + embedding_model.

### ai_agents_aiagent (WorkspaceOwned)
* Config: `instructions` (private), `provider`, `model`, `effort`, `max_output_tokens`, knowledge scope
  (`use_all_knowledge`, M2M `knowledge_sources`, `retrieval_top_k`, `min_relevance`,
  `answer_only_from_knowledge`), tone, handoff rules (`handoff_confidence_threshold`, `handoff_on_no_knowledge`,
  `handoff_keywords` text[], `max_ai_replies`, `handoff_team` SET NULL, `handoff_message`,
  `allow_after_human_takeover`), `enabled`, `is_deployed`.
* **Partial unique** `(workspace) WHERE is_deployed` — one live agent per workspace.

### ai_agents_aiexecution / ai_agents_toolexecution (WorkspaceOwned)
* Execution: `agent` (SET NULL), `source` (conversation/playground/summary), `conversation` (CASCADE),
  `trigger_message`, `response_message`, `status` (answered/handed_off/skipped/quota_exceeded/failed),
  `skip_reason`, `provider`, `model`, tokens, `latency_ms`, `confidence`, `handoff_reason`, `query`, `answer`,
  `retrieved` (JSONB chunk refs + scores), `steps` (JSONB graph trace), `error`.
* ToolExecution: `execution` (CASCADE), `tool_name`, `arguments`, `result`, `status`, `latency_ms`.

### workflows_workflow / workflows_workflowexecution (WorkspaceOwned)
* Workflow: `trigger`, `trigger_config`, `conditions` (JSONB), `actions` (JSONB), `enabled`, `position`,
  `run_count`, `last_run_at`. Index `(workspace, trigger, enabled)`.
* Execution: `workflow` (CASCADE), `conversation`, `status`, `results`, **unique `dedupe_key`**.

### integrations_integration / integrations_integrationdelivery (WorkspaceOwned)
* Integration: `kind` (webhook/slack), `url_encrypted`, `url_host` (display), `signing_secret_encrypted`,
  `events` text[], `consecutive_failures`, `enabled`.
* Delivery: `event`, `payload`, `status`, `attempts`, `response_status`, `error`, `delivered_at`.

### billing (organization-level)
* `billing_plan`: `code` unique, `prices` (minor units per currency), `limits`, `features`,
  `provider_prices`, `trial_days`, `is_public`, `is_trial`.
* `billing_subscription`: one per organization; `plan` PROTECT, `status`, `provider`, provider ids,
  `currency`, period, `trial_ends_at`, `cancel_at_period_end`.
* `billing_usageledger` (**append-only**): `organization`, `workspace_id`, `metric`, `quantity` (check ≥ 0),
  **unique `idempotency_key`**, `source_type/id`, `occurred_at`. Index `(organization, metric, occurred_at)`.
* `billing_invoice`: **unique `(provider, provider_invoice_id)`**, amount (minor), currency, status, hosted URL.
* `billing_webhookevent`: **unique `(provider, event_id)`**, `status`, `attempts`, `error`, payload.

## Deletion behaviour

| Parent deleted | Effect |
|---|---|
| Organization | cascades memberships, invitations, workspaces (+ their memberships). Audit logs remain. |
| Workspace | cascades workspace memberships and workspace-targeted invitations. |
| User | cascades memberships; `created_by`, `invited_by`, `accepted_by`, `actor`, message authors and assignees set NULL. |
| Customer | cascades identities, notes and conversations (with their messages, attachments and events). Admin-only (`workspace.update`). |
| Tag / Team | removed from M2M links; conversations keep existing (team set NULL). |

Hard deletion of organizations is not exposed via the API; it will be a deliberate, audited,
asynchronous offboarding job (Phase 5).

## Planned entities (by phase)

* **Phase 5**: DB-level append-only enforcement (REVOKE UPDATE/DELETE) for audit and usage ledgers,
  Row-Level Security, partitioning for messages/usage at scale.
