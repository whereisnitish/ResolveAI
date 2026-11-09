from __future__ import annotations

import secrets
import uuid
from collections.abc import Callable

from django.utils.text import slugify


def unique_slug(value: str, exists: Callable[[str], bool], max_length: int = 60, fallback: str = "item") -> str:
    """Slugify ``value`` and append a short random suffix until ``exists`` is False."""
    base = slugify(value)[:max_length].strip("-") or fallback
    candidate = base
    while exists(candidate):
        candidate = f"{base[: max_length - 7]}-{secrets.token_hex(3)}"
    return candidate


def parse_uuid(value: object) -> uuid.UUID | None:
    """Parse a UUID from untrusted input; None when malformed (callers return empty results)."""
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        return None
