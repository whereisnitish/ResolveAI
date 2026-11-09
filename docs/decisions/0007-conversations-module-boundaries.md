# ADR-0007: Module boundaries for customers, conversations and messaging

* Status: Accepted · Date: 2026-11-09

## Context
The suggested structure listed separate `conversations` and `messaging` apps, plus tags and teams used by several modules.

## Decision
* **Messages live in `apps.conversations`.** A message has no lifecycle outside its conversation, and every write updates conversation state (last message, first response, reopen) in the same transaction. Splitting them would create a circular dependency or a distributed transaction for no benefit.
* **Real-time delivery lives in `apps.realtime`**: consumers, routing and publish helpers, with no models. This is the "messaging transport" concern.
* **Tags and Teams live in `apps.workspaces`**. They are workspace-level configuration used by customers, conversations and, later, workflows and analytics. Putting them in `conversations` would make `customers` depend on `conversations`.
* **`apps.widget`** owns the public visitor API, visitor auth and `WidgetSettings`, and calls the conversation and customer services. Nothing in the core domain imports the widget except one lazy import for the visitor message payload.
* Dependency direction: `widget → conversations → customers → workspaces → organizations → accounts`.

## Consequences
* \+ No import cycles; each app's service layer is the only entry point for writes.
* − `conversations` is the largest app; if it grows (e.g. email channel), channel adapters can move into their own apps without touching storage.
