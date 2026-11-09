# ADR-0009: Billing via provider abstraction and an append-only usage ledger

* Status: Accepted · Date: 2026-11-09

## Context
Customers in India pay through Razorpay (INR); international customers pay through Stripe. Usage (AI replies, tokens, storage, seats) must be metered reliably and must never come from the client.

## Decision
* **Plans** are data (a seeded catalog that heals itself if rows go missing), with per-currency prices in minor units and limits (`seats`, `workspaces`, `ai_executions_per_month`, `knowledge_mb`). New organizations get a 14-day trial. When the trial expires or the subscription is canceled, *inactive* limits apply: the inbox keeps working and AI pauses.
* **Providers** (`apps/billing/providers.py`) implement `create_checkout` and `parse_webhook`. Stripe checkout and Razorpay subscriptions are created over each provider's REST API via httpx.
  * Stripe signatures (`t=…,v1=HMAC(secret, "t.body")`, 5-minute tolerance) and Razorpay signatures (`HMAC(secret, body)`) are verified before parsing.
  * Payloads are normalized into provider-agnostic `BillingEvent`s, so subscription logic exists once (`services.apply_event`).
  * Country `IN` routes to Razorpay, everything else to Stripe. A signed **mock** provider exercises the identical webhook pipeline in development (disabled in production).
* **Idempotency** (brief test #6): `WebhookEvent` is unique on `(provider, event_id)` and handled with `get_or_create` under `select_for_update`. Already processed or ignored events are no-ops; failed events are retried on redelivery (the endpoint returns 500 so the provider redelivers). Invoices are unique on `(provider, provider_invoice_id)`.
* **Usage ledger** (`UsageLedger`): append-only rows (the model refuses update and delete; a DB check enforces `quantity ≥ 0`) with a unique `idempotency_key` (e.g. `aiexec:<id>:in`), so retries never double-count. Quantities are computed server-side from executions and ingestion. Seats, workspaces and knowledge storage are computed live.
* **Enforcement** is server-side at the action boundary: invitations (seats including pending invites), workspace creation, knowledge uploads (MB) and AI execution (monthly replies, checked before any model call). Errors return HTTP 402 with `code: plan_limit_reached`.
* **Billing period:** usage counts within the subscription's current period (else the calendar month); an upgrade starts a new period.

## Consequences
* \+ Adding a payment provider means one class; webhooks are safe to replay.
* \+ The ledger gives an auditable, reconstructable basis for invoices and usage-based pricing.
* − Stripe/Razorpay customer portal, proration, tax/GST invoices and dunning emails are not built yet.
* − Razorpay requires plan ids to be configured per plan and currency (Django admin → `Plan.provider_prices`).
