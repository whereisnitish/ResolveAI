"""Per-account login throttling.

The IP-scoped "auth" throttle stops one client hammering the API; this stops a
distributed credential-stuffing run (many IPs) against a single account. After
LOGIN_LOCKOUT_THRESHOLD failures inside the window, further attempts for that email
are rejected *before* the password is checked, until the window expires.

Trade-off: an attacker can deliberately lock a victim out for one window. The
window is short (15 min by default) and the lock is per-email, not per-IP, so the
cost to the victim is bounded; a password reset is never blocked.
"""

from __future__ import annotations

import hashlib

from django.conf import settings
from django.core.cache import cache


def _key(email: str) -> str:
    # Hash so raw emails never sit in the cache keyspace.
    return "login-fail:" + hashlib.sha256(email.lower().encode()).hexdigest()


def is_locked(email: str) -> bool:
    return int(cache.get(_key(email), 0)) >= settings.LOGIN_LOCKOUT_THRESHOLD


def register_failure(email: str) -> int:
    key = _key(email)
    window = settings.LOGIN_LOCKOUT_WINDOW_SECONDS
    if cache.add(key, 1, timeout=window):
        return 1
    try:
        return int(cache.incr(key))
    except ValueError:  # expired between add() and incr()
        cache.set(key, 1, timeout=window)
        return 1


def reset(email: str) -> None:
    cache.delete(_key(email))
