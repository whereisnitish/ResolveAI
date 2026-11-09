# ADR-0001: Modular monolith (Django) with a thin Next.js frontend

* Status: Accepted · Date: 2026-11-09

## Context
ResolveAI spans many domains (accounts, tenancy, inbox, widget, AI, knowledge, billing...). The
team is small and the product is pre-revenue. We need fast iteration with strong consistency
(e.g. registration creates user + org + workspace atomically; usage ledger and billing must be
transactionally correct).

## Decision
One Django project with domain apps under `backend/apps/`, a shared PostgreSQL database, Celery
for async work and Channels for real-time. Business logic lives in per-app `services.py`.
Cross-cutting concerns live in `common/` and the `apps/tenancy` access layer. The Next.js app
serves UI only and proxies API calls.

## Consequences
* + Simple deploys, local dev and transactions; refactoring across modules is cheap.
* + Clear seams (services, tenancy layer) allow extraction later (e.g. AI execution workers).
* − Requires discipline: apps must not reach into each other's internals; imports flow
  `views → services → models`, and cross-domain calls go through services.
* − Scaling is per process type (web, worker, beat), not per domain — acceptable at this stage.
