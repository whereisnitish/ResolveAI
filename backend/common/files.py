"""Upload validation: extension allowlist + content signature + size limit.

We never trust the client's Content-Type. The stored content type is derived
from the validated extension, and the file's leading bytes must match it.
SVG/HTML and other active content are rejected outright.
"""

from __future__ import annotations

import os
import re
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass

from django.conf import settings
from django.core.files.uploadedfile import UploadedFile
from rest_framework.exceptions import ValidationError


def _starts(*prefixes: bytes) -> Callable[[bytes], bool]:
    return lambda head: any(head.startswith(p) for p in prefixes)


def _is_webp(head: bytes) -> bool:
    return head[:4] == b"RIFF" and head[8:12] == b"WEBP"


def _is_text(head: bytes) -> bool:
    if b"\x00" in head:
        return False
    try:
        head.decode("utf-8")
    except UnicodeDecodeError as exc:
        # Allow a multi-byte character cut off at the sniff boundary.
        return exc.start >= len(head) - 3
    return True


@dataclass(frozen=True)
class FileType:
    content_type: str
    check: Callable[[bytes], bool]
    inline: bool = False  # safe to display inline (raster images only)


ALLOWED_TYPES: dict[str, FileType] = {
    ".png": FileType("image/png", _starts(b"\x89PNG\r\n\x1a\n"), inline=True),
    ".jpg": FileType("image/jpeg", _starts(b"\xff\xd8\xff"), inline=True),
    ".jpeg": FileType("image/jpeg", _starts(b"\xff\xd8\xff"), inline=True),
    ".gif": FileType("image/gif", _starts(b"GIF87a", b"GIF89a"), inline=True),
    ".webp": FileType("image/webp", _is_webp, inline=True),
    ".pdf": FileType("application/pdf", _starts(b"%PDF-")),
    ".txt": FileType("text/plain", _is_text),
    ".csv": FileType("text/csv", _is_text),
    ".md": FileType("text/markdown", _is_text),
    ".docx": FileType(
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document", _starts(b"PK\x03\x04")
    ),
    ".xlsx": FileType("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", _starts(b"PK\x03\x04")),
}


@dataclass(frozen=True)
class ValidatedUpload:
    file: UploadedFile
    filename: str
    content_type: str
    size: int


def sanitize_filename(name: str) -> str:
    name = unicodedata.normalize("NFKC", os.path.basename(name or "")).strip()
    name = re.sub(r"[^\w.\- ()]+", "_", name)[:200].strip(". ")
    return name or "file"


def validate_upload(
    upload: UploadedFile,
    *,
    allowed_extensions: set[str] | None = None,
    max_bytes: int | None = None,
    field: str = "files",
) -> ValidatedUpload:
    filename = sanitize_filename(upload.name or "")
    ext = os.path.splitext(filename)[1].lower()
    permitted = {e: t for e, t in ALLOWED_TYPES.items() if allowed_extensions is None or e in allowed_extensions}
    file_type = permitted.get(ext)
    if file_type is None:
        allowed = ", ".join(sorted(permitted))
        raise ValidationError({field: [f"File type not allowed: {filename}. Allowed: {allowed}."]})
    max_bytes = max_bytes or settings.ATTACHMENT_MAX_BYTES
    if upload.size is None or upload.size > max_bytes:
        raise ValidationError({field: [f"{filename} exceeds the {max_bytes // (1024 * 1024)} MB limit."]})
    if upload.size == 0:
        raise ValidationError({field: [f"{filename} is empty."]})
    upload.seek(0)
    head = upload.read(4096)
    upload.seek(0)
    if not file_type.check(head):
        raise ValidationError({field: [f"{filename} does not look like a valid {ext} file."]})
    return ValidatedUpload(file=upload, filename=filename, content_type=file_type.content_type, size=upload.size)


def is_inline_safe(content_type: str) -> bool:
    return any(t.inline and t.content_type == content_type for t in ALLOWED_TYPES.values())
