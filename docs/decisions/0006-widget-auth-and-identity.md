# ADR-0006: Website widget authentication and visitor identity

* Status: Accepted · Date: 2026-11-09

## Context
The widget runs on customers' websites, in an environment we don't control. It must never expose API keys, must be scoped to one workspace and one visitor, and must not let a visitor become someone else.

## Decision
**Credentials**
* `public_id` (`ws_…`) identifies the workspace in the snippet. It is public and not a secret.
* **Visitor token**: a 256-bit random value stored in the visitor's browser (`localStorage`). Only its SHA-256 is stored (`CustomerIdentity`). It is used solely to obtain a session.
* **Session token**: Django-signed (salted, versioned), carrying workspace + customer + identity IDs, and expiring after 1 h (`WIDGET_SESSION_TTL_SECONDS`). It is sent as `Authorization: Bearer` and refreshed automatically on 401.
* Every request re-checks the signature and expiry, that the identity still maps to the same customer and workspace, that the workspace isn't archived, that the widget is enabled, and that the `Origin` is in the workspace's `allowed_origins`.

**Isolation**
* Every widget query is filtered by workspace **and** customer. Another visitor's conversation IDs return 404.
* Visitor-facing serializers expose replies only: never internal notes, agent emails, tags, assignment data or workspace and organization IDs.
* The widget API ignores dashboard cookies (bearer-only auth) and has its own CORS policy (any origin, never credentials). Origin authorization is enforced per workspace in the views.
* Rate limits per visitor (or per IP before a session exists): session 30/min, writes 30/min, reads 120/min.

**Identity**
* A visitor can self-report a name and email (`identify`). This is **unverified**: it only updates *their own* customer record and never merges with or reveals an existing customer that has the same email. Otherwise anyone could read a CEO's history by typing their address.
* Verified identity, where the customer's backend signs `user_id` with a workspace secret (HMAC) so we can merge, is planned. `Customer.external_id` is reserved for it.

**Origins**
* An empty `allowed_origins` list means any origin is allowed, to keep first-time setup easy. The dashboard shows a warning until domains are configured. Origin checks only constrain browsers; abuse from scripts is bounded by rate limits and per-visitor scoping.

## Consequences
* \+ A leaked session token is useless after an hour and only ever covered one visitor in one workspace.
* \+ Disabling the widget or changing allowed origins revokes live sessions immediately.
* − Anonymous visitors create customer rows eagerly; a cleanup job for idle anonymous visitors with no conversations is planned.
