# ADR-0005: Real-time via Channels with ID-only dashboard events

* Status: Accepted · Date: 2026-11-09

## Context
The shared inbox needs live updates (new conversations and messages, status and assignment changes, typing). Dashboard sockets are long-lived, but a member's access can change at any time (deactivated, removed, role downgraded). Website visitors also need live replies.

## Decision
* Django Channels with the Redis channel layer. There is one group per workspace (`workspace.<id>`) and one per visitor (`visitor.<customer_id>`).
* **Dashboard events carry identifiers only**, e.g. `{type: "message.created", conversation_id, message_id}`. Clients refetch through the REST API, which re-authorizes every call. A socket that outlives its permissions therefore learns at most that something changed, never the content.
* **Visitor events carry message payloads**, limited to that visitor's own non-internal replies, because the widget has no other low-latency channel.
* Events are published with `transaction.on_commit`, so rolled-back writes never reach clients.
* Dashboard sockets authenticate with the session cookie. The handshake `Origin` must be one of `CSRF_TRUSTED_ORIGINS`, which prevents cross-site WebSocket hijacking. Membership is resolved at connect time.
* Widget sockets authenticate with the widget session token sent **as the first frame**, never in the URL, so it can't leak into access logs. Unauthenticated sockets close after 10 s.
* Typing signals are relayed in both directions and rate-limited per socket. An agent typing an *internal note* is never signalled to the visitor.

## Consequences
* \+ No cross-tenant or stale-permission leakage over sockets; the REST layer stays the single authority.
* \+ The frontend is simple: events invalidate TanStack Query caches.
* − An extra REST round-trip per event (acceptable; payloads are small and paginated).
* Operational note: channels_redis blocks on `BZPOPMIN` for 5 s. redis-py ≥ 8 defaults `socket_timeout` to 5 s, which races and kills consumers. The layer is configured with `socket_timeout: 30`, and a regression test (`tests/test_channel_layer_redis.py`) runs against real Redis.
