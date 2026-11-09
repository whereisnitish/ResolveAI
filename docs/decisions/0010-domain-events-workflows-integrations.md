# ADR-0010: In-process domain events for AI, workflows and integrations

* Status: Accepted · Date: 2026-11-09

## Context
New features (the AI auto-reply, workflow automation, outgoing integrations) all react to conversation activity. Calling them directly from `conversations.services` would make the core domain depend on every feature module.

## Decision
* `common/events.py` provides `subscribe(event, handler)` and `emit(event, **payload)`. Emission runs handlers **after commit** (`transaction.on_commit`); handler failures are logged and isolated.
* The conversation services emit `conversation.created`, `message.created`, `conversation.status_changed` and `conversation.assigned`, each with a `source` (`user`, `customer`, `ai`, `workflow`, `system`).
* Feature apps subscribe in `AppConfig.ready()` and only enqueue Celery tasks (`ai_reply_task`, `dispatch_workflows_task`, `fan_out_task`).
* **Loop prevention:** workflow actions use `Actor.system(source="workflow")`, and the workflow subscriber ignores events whose source is `workflow`. Workflows therefore can't trigger workflows, while integrations still see the resulting changes.
* **Workflows** are declarative JSON validated against a fixed schema: a trigger, conditions over whitelisted fields and operators, and a fixed set of actions. Referenced users, teams and tags must belong to the workspace, at save time and again at run time. Each run has a unique `dedupe_key` per occurrence, so retries and the periodic "customer waiting" scan (Celery beat, every minute) are idempotent. There is no arbitrary code execution.
* **Integrations:**
  * Destination URLs are encrypted at rest (Fernet, `FIELD_ENCRYPTION_KEY`).
  * Deliveries go through the SSRF-safe HTTP client and are HMAC-signed (`X-ResolveAI-Signature: t=…,v1=…`).
  * Failed deliveries retry with exponential backoff (5 attempts). An endpoint is auto-disabled after 50 consecutive failures.
  * Every attempt is logged per delivery.

## Consequences
* \+ The core stays independent; features can be added or removed by subscription.
* \+ Each side effect is asynchronous, retryable and observable.
* − An in-process bus is not a durable event log. If a crash happens between commit and enqueue, an event can be lost. A transactional outbox is the Phase 5+ upgrade path if stricter delivery guarantees are needed.
