# ADR-0003: Cookie sessions with a same-origin API proxy (no JWT in the browser)

* Status: Accepted · Date: 2026-11-09

## Context
The dashboard needs secure authentication. Common choices: JWTs in localStorage, JWTs in
cookies, or server-side sessions.

## Decision
Use Django server-side sessions in an **HttpOnly, SameSite=Lax, Secure (prod)** cookie. The
browser only talks to the Next.js origin; Next rewrites `/api/*` to Django
(`BACKEND_INTERNAL_URL`). CSRF is enforced with Django's double-submit token for every unsafe
request, including anonymous login/registration. `CSRF_TRUSTED_ORIGINS` must list the dashboard
origin(s) because Django sees the proxied request with the backend host.

## Consequences
* + Tokens are not readable by JavaScript (XSS can't exfiltrate a session token).
* + Instant revocation (logout, password change, deactivation) — no token-expiry window.
* + No CORS needed for the dashboard in the standard deployment.
* − Needs the proxy (or the same parent domain) in every environment.
* The **widget** will NOT use these sessions: it gets short-lived, workspace-scoped visitor
  tokens on a separate public API (Phase 2). Public API keys for server-to-server integrations
  are a separate future mechanism.
