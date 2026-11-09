# ADR-0011: Append-only ledgers enforced in PostgreSQL; RLS deferred

* Status: Accepted · Date: 2026-11-09

## Context

Two tables carry legal and financial weight. `audit_auditlog` is the security trail, and `billing_usageledger` is the source of truth for metered billing. Until Phase 4, immutability was enforced only by the ORM: `UsageLedger.save()/delete()` raise. But `QuerySet.update()`, `QuerySet.delete()`, raw SQL, a future admin action or a compromised code path all bypass model methods.

We also reviewed PostgreSQL Row-Level Security (RLS) as defence in depth for tenant isolation.

## Decision

1. **Triggers.** A plpgsql trigger function, `resolveai_append_only()`, is attached `BEFORE UPDATE OR DELETE` to both tables (migrations `audit.0002`, `billing.0003`). It raises `insufficient_privilege` with the message `<table> is append-only`. There are two narrow exceptions:
   * **Audit actor erasure.** An UPDATE is allowed only if the *only* changed column is `actor_id` and its new value is NULL. That is exactly what `ON DELETE SET NULL` does when a user is erased. The trail keeps `actor_email`.
   * **Explicit purge.** DELETE is allowed only inside `common.db.allow_purge()`, which sets the transaction-local GUC `resolveai.allow_purge=on` and resets it on exit. It exists for tenant erasure and retention jobs, which must themselves be audited. `TRUNCATE` (used by test teardown) does not fire row triggers.
2. **RLS is deferred.** Tenant isolation stays in the application layer: scoped querysets, central RBAC, and 404 for foreign tenants. It is covered by the 7 critical cross-tenant tests and per-endpoint isolation suites. RLS would require:
   * setting a per-request GUC (`app.workspace_id`) on every connection checkout, which interacts badly with connection pooling and transaction-mode PgBouncer
   * a separate non-owner database role for the app
   * policies on about 40 tables, kept in sync with the models
   * bypass handling for Celery tasks that legitimately cross workspaces (billing aggregation, beat scans)

   The risk-to-benefit balance favours doing it later, when an external audit or enterprise contract requires it.

## Consequences

* \+ History can't be rewritten by bugs, raw SQL or a hijacked request path; only a DBA disabling the trigger could, and that leaves its own trail.
* \+ Tests prove that `update()`, raw `DELETE` and multi-column updates are rejected, that user erasure works, and that the purge flag doesn't leak beyond its scope (`tests/test_production_readiness.py`).
* − Correcting a mis-metered usage entry means appending a compensating entry, not editing. This is intended for a ledger.
* − RLS remains a documented gap. Isolation depends on application code, which the test suites guard. Upgrade path: introduce the app role and policies for the highest-value tables first (`conversations_*`, `customers_*`, `knowledge_*`), with `SET LOCAL` in a `connection_created`/request middleware.
