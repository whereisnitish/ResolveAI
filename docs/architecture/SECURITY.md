# ResolveAI — Security

_Last updated: 2026-11-09 (through Phase 4)._ Status legend: ✅ implemented & tested · 🟡 partial · ⏳ planned.

## Tenant isolation

| Control | Status |
|---|---|
| Every tenant request resolves access from the authenticated user + DB memberships (`apps/tenancy`) | ✅ |
| Tenant IDs in URLs are never trusted; unauthorized/unknown tenants → 404 (no existence oracle) | ✅ |
| Default-deny: view actions without a declared permission are rejected | ✅ |
| Nested object lookups always filter by the resolved tenant (IDOR) | ✅ |
| Serializer FK choices restricted to the caller's org (e.g. invitation workspace, member add) | ✅ |
| Inactive org membership revokes org **and** all workspace access, overriding workspace memberships | ✅ |
| Archived workspaces inaccessible | ✅ |
| `WorkspaceOwnedModel` derives org from workspace and rejects mismatches | ✅ |
| PostgreSQL Row-Level Security as defense-in-depth | ⏳ Phase 5 (see ADR-0002) |

Critical tests live in `backend/tests/test_tenant_isolation.py`; the suite was mutation-checked
(disabling the `is_active` filter or the role check makes it fail).

### Phase 2 additions
| Control | Status |
|---|---|
| All 30 workspace-scoped Phase 2 endpoints: foreign workspace -> 404; foreign object ids under own workspace -> 404 (IDOR) | ✅ `test_phase2_isolation.py` |
| Cross-workspace references rejected (tags, teams, assignees, customers, team members) | ✅ |
| Role matrix (viewer read-only, agent reply/assign, supervisor manages tags) | ✅ |
| Assignees must hold `conversations.reply` in the workspace | ✅ |

## Website widget (ADR-0006)
| Control | Status |
|---|---|
| No API keys in the snippet; only the public `public_id` | ✅ |
| Short-lived (1 h) signed, salted session token bound to workspace + customer + identity | ✅ tested (expiry, tampering, mixed ids) |
| Visitor token stored only as SHA-256 | ✅ |
| **Widget token cannot access another workspace** (critical test #4) | ✅ mutation-checked |
| Visitor cannot read another visitor's conversations or attachments in the same workspace | ✅ |
| Internal notes and their attachments never reach visitors (REST + WebSocket) | ✅ |
| Per-workspace origin allowlist enforced on session, every API call and the socket | ✅ |
| Disabling the widget or changing origins revokes live sessions immediately | ✅ |
| Separate CORS (any origin, never credentials); dashboard cookies ignored by the widget API | ✅ |
| Rate limits per visitor/IP (session 30/min, write 30/min, read 120/min) | ✅ tested |
| Unverified identify never merges with or reveals other customers | ✅ tested |
| Widget renders all content as text (no HTML path); brand colour validated | ✅ widget unit tests |
| HMAC identity verification for logged-in users | ⏳ |

## Real-time (ADR-0005)
| Control | Status |
|---|---|
| Dashboard socket: session auth, and Origin must be a dashboard origin (CSWSH) | ✅ tested + live |
| Dashboard events are ID-only; data is always refetched via authorized REST | ✅ |
| Widget socket token sent as the first frame (not in URLs/logs); 10 s auth timeout | ✅ |
| Typing relay limited to own workspace/conversation, rate-limited, notes hidden | ✅ |

## File uploads
| Control | Status |
|---|---|
| Extension allowlist + magic-byte check; client Content-Type ignored; SVG/HTML/executables rejected | ✅ tested |
| Size (10 MB) and count (5) limits | ✅ |
| Random storage keys; private S3 ACL; no public media route | ✅ |
| Downloads only via authorized endpoints with `nosniff`, `CSP: sandbox`, attachment disposition for non-images | ✅ |
| Malware scanning (e.g. ClamAV / GuardDuty for S3) | ⏳ Phase 5 |

## AI (ADR-0008)
| Control | Status |
|---|---|
| **AI cannot reply after a human took control** (critical test #7) — re-checked under row lock at delivery | ✅ mutation-checked |
| Agent instructions never sent to visitors; answers echoing them are blocked (shingle overlap) | ✅ tested |
| Internal notes excluded from model context | ✅ tested |
| Retrieved knowledge / tool results framed as data (prompt-injection mitigation) | ✅ |
| Tools: read-only, workspace-scoped, argument-validated; unknown tools rejected; no code execution | ✅ tested |
| Knowledge retrieval cannot cross workspaces (even with foreign source ids) | ✅ tested |
| Provider refusals, errors, low confidence → human handoff (no unsafe fallback text) | ✅ tested |
| No mock fallback in production (`AI_ALLOW_MOCK_FALLBACK=False`) | ✅ prod settings |
| Usage quotas enforced before any model call | ✅ tested |

## Knowledge ingestion & outbound HTTP
| Control | Status |
|---|---|
| SSRF-safe client: http(s) only, no credentials, std ports, all resolved IPs must be public (blocks loopback, RFC1918, link-local/metadata, CGNAT, IPv4-mapped), manual redirect re-validation, size/time caps | ✅ tested |
| Knowledge uploads: PDF/TXT/MD allowlist + magic bytes, 20 MB cap, private storage, plan storage quota | ✅ tested |
| HTML stripped of scripts/nav before indexing | ✅ tested |
| DNS-rebinding TOCTOU between check and connect | 🟡 residual; mitigate with egress firewall (Phase 5) |

## Billing (ADR-0009)
| Control | Status |
|---|---|
| Stripe (timestamped HMAC, 5-min tolerance) and Razorpay (HMAC) webhook signatures verified before parsing | ✅ tested (bad secret, stale, tampered) |
| **Duplicate webhooks processed once** (critical test #6) | ✅ mutation-checked |
| Usage computed server-side only; append-only, idempotent ledger | ✅ tested |
| Plan limits enforced server-side (seats, workspaces, knowledge, AI) → HTTP 402 | ✅ tested |
| Checkout only for owners / billing admins; mock provider disabled in production | ✅ |

## Workflows & integrations (ADR-0010)
| Control | Status |
|---|---|
| Declarative workflows only — fixed fields/operators/actions, no code execution | ✅ tested |
| Referenced users/teams/tags validated against the workspace at save and run time | ✅ tested |
| Workflows cannot trigger workflows (loop prevention); runs deduplicated | ✅ tested |
| Integration URLs/secrets encrypted at rest (Fernet; key required in prod); URL never returned | ✅ tested |
| Webhook payloads HMAC-signed; SSRF-safe delivery; retries with backoff; auto-disable on persistent failure | ✅ tested |

## Authentication & sessions

| Control | Status |
|---|---|
| Argon2id password hashing; Django password validators (min 10) | ✅ |
| HttpOnly, SameSite=Lax session cookie; `Secure` in prod | ✅ |
| Session rotation on login (fixation) | ✅ tested |
| Other sessions invalidated on password change/reset | ✅ tested |
| CSRF on all unsafe requests incl. anonymous login/register (login-CSRF) | ✅ tested |
| CSRF trusted origins restricted to the dashboard origin(s) | ✅ verified end-to-end |
| No account enumeration on password reset; uniform login failure message | ✅ tested |
| Email verification token bound to current email, expiring | ✅ tested |
| Invitation tokens: 256-bit random, only SHA-256 stored, single use, expiring, email-bound | ✅ tested |
| Rate limiting on auth endpoints (Redis-backed DRF throttles) | ✅ tested |
| MFA / SSO (SAML/OIDC) | ⏳ |
| Per-account lockout (10 failures / 15 min, checked before the password; `429 login_locked`) | ✅ tested |
| Anomaly detection | ⏳ |

## Authorization

* Single RBAC registry (`common/rbac.py`); views declare permissions, never compare roles.
* Owner-only operations (grant/modify Owner, billing manage, delete org) and last-owner protection
  under a row lock. ✅ tested
* Frontend uses permissions only to hide UI; the backend re-checks everything.

## Input, output and errors

* DRF serializers validate all input; UUID path converters; timezone/country validated.
* Uniform error envelope; unhandled exceptions return a generic message (no stack traces) — ✅ tested.
* Request IDs on every response for support/forensics.

## Transport & headers

* Prod settings: HSTS (1y, preload), SSL redirect, secure cookies, `X-Frame-Options: DENY`,
  nosniff, strict referrer policy; `manage.py check --deploy` passes with a real secret key.
* Next.js sends nosniff, frame-deny, referrer and permissions policy headers.
* CORS: credentialed requests only from configured dashboard origins and only on `/api/*`.
* Client IP for audit/throttling honours `X-Forwarded-For` only for `TRUSTED_PROXY_COUNT`
  proxies (prevents IP spoofing) — ✅ tested.
* API responses carry `Content-Security-Policy: default-src 'none'; frame-ancestors 'none'; sandbox`, `Cache-Control: no-store`, CORP (`same-site`, or `cross-origin` for the widget API) and Permissions-Policy. ✅ tested
* The dashboard sends a CSP (`script-src 'self' 'unsafe-inline'`, `connect-src` limited to self and the WebSocket origin, `frame-ancestors 'none'`, `object-src 'none'`) and COOP `same-origin`. ✅ verified on the production image. ADR-0012 covers the `'unsafe-inline'` trade-off.
* `manage.py check --deploy` includes ResolveAI checks E001–E008: DEBUG, weak secret, wildcard hosts, non-https origins, mock AI or billing, and an invalid Fernet key. The `migrate` one-shot refuses to start on any of these errors. ✅ tested

## Audit logging

Append-only `AuditLog` for: registration, login success/failure, logout, email verification,
password reset request/complete, password change, org create/update, member role/status change
and removal, invitation create/revoke/accept, workspace create/update, workspace member
add/update/remove. Visible to Owners/Admins via `/organizations/{id}/audit-logs/`.

**Database-enforced immutability (ADR-0011):** triggers reject UPDATE and DELETE on `audit_auditlog` and `billing_usageledger`, including raw SQL. The only exceptions are nulling `actor_id` when a user is erased, and deletes inside `common.db.allow_purge()`. ✅ tested

## Secrets

* All secrets come from environment variables; `.env` is git-ignored; `.env.example` contains
  placeholders only. Production should inject secrets from AWS Secrets Manager/SSM.
* Raw invitation tokens and passwords are never stored or logged.

## Upcoming security work by phase

* **Done in Phase 5:**
  * CSP and API security headers
  * Sentry with PII scrubbing (`send_default_pii=False`; a scrubber drops request bodies and cookies and redacts auth headers and query strings)
  * dependency scanning in CI (`pip-audit`, `npm audit`)
  * tested backup and restore scripts
  * DB-level append-only ledgers
  * per-account lockout
* **Next:** RLS (deferred, ADR-0011), MFA/SSO, nonce-based CSP, anomaly detection, WAF rules, a tenant erasure command.
