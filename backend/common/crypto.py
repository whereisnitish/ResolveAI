"""Symmetric encryption for secrets stored in the database (integration URLs/tokens).

Key: FIELD_ENCRYPTION_KEY (urlsafe base64, 32 bytes — `Fernet.generate_key()`).
When unset (local dev/tests) a key is derived from SECRET_KEY; production settings
require an explicit key so rotating SECRET_KEY doesn't make secrets unreadable.
"""

from __future__ import annotations

import base64
import hashlib
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings


@lru_cache(maxsize=1)
def _fernet() -> Fernet:
    key = getattr(settings, "FIELD_ENCRYPTION_KEY", "") or ""
    if not key:
        digest = hashlib.sha256(f"resolveai-field-encryption:{settings.SECRET_KEY}".encode()).digest()
        key = base64.urlsafe_b64encode(digest).decode()
    return Fernet(key.encode() if isinstance(key, str) else key)


def encrypt(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode() if value else ""


def decrypt(token: str) -> str:
    if not token:
        return ""
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken as exc:
        raise ValueError("Stored secret could not be decrypted (key changed?)") from exc
