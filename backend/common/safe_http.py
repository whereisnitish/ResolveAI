"""Outbound HTTP to user-supplied URLs (knowledge crawling, webhooks) with SSRF protection.

Rules:
* http/https only; no credentials in URLs; standard ports only unless explicitly allowed.
* Every hostname is resolved and *all* addresses must be public (no loopback, private,
  link-local incl. cloud metadata 169.254.169.254, multicast, reserved, CGNAT).
* Redirects are followed manually (max 3), re-validating each hop.
* Response size and time are capped.

Residual risk: DNS rebinding between our check and the connection. Mitigated in
production by egress restrictions (see docs/architecture/SECURITY.md).
"""

from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit

import httpx
from django.conf import settings

MAX_REDIRECTS = 3
USER_AGENT = "ResolveAI/1.0 (+https://resolveai.com/bot)"


class UnsafeURLError(ValueError):
    """The URL points somewhere we refuse to connect to."""


@dataclass(frozen=True)
class SafeResponse:
    url: str
    status_code: int
    content_type: str
    body: bytes


def _is_public(ip: str) -> bool:
    addr = ipaddress.ip_address(ip)
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped:
        addr = addr.ipv4_mapped
    return addr.is_global and not addr.is_multicast


def validate_url(url: str, *, allow_http: bool | None = None) -> str:
    """Validate syntax and resolve the host; raise UnsafeURLError if unsafe."""
    parts = urlsplit(url.strip())
    allow_http = settings.DEBUG if allow_http is None else allow_http
    allowed_schemes = {"https", "http"} if allow_http else {"https"}
    if parts.scheme not in allowed_schemes:
        raise UnsafeURLError(f"URL scheme must be one of: {', '.join(sorted(allowed_schemes))}.")
    if not parts.hostname:
        raise UnsafeURLError("URL must include a host.")
    if parts.username or parts.password:
        raise UnsafeURLError("URLs with embedded credentials are not allowed.")
    if parts.port not in (None, 80, 443) and not getattr(settings, "SAFE_HTTP_ALLOW_ANY_PORT", False):
        raise UnsafeURLError("Only standard HTTP(S) ports are allowed.")
    if parts.hostname.lower() in {"localhost", "localhost.localdomain"} or parts.hostname.endswith(".local"):
        raise UnsafeURLError("Local addresses are not allowed.")
    try:
        infos = socket.getaddrinfo(parts.hostname, parts.port or (443 if parts.scheme == "https" else 80))
    except socket.gaierror as exc:
        raise UnsafeURLError("The host could not be resolved.") from exc
    addresses = {info[4][0] for info in infos}
    if not addresses or not all(_is_public(a) for a in addresses):
        raise UnsafeURLError("The URL resolves to a private or reserved network address.")
    return url.strip()


def safe_request(
    method: str,
    url: str,
    *,
    json: object | None = None,
    content: bytes | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = 10.0,
    max_bytes: int = 2 * 1024 * 1024,
    allow_http: bool | None = None,
    transport: httpx.BaseTransport | None = None,
) -> SafeResponse:
    current = validate_url(url, allow_http=allow_http)
    hdrs = {"User-Agent": USER_AGENT, **(headers or {})}
    with httpx.Client(timeout=timeout, follow_redirects=False, transport=transport) as client:
        for _ in range(MAX_REDIRECTS + 1):
            with client.stream(method, current, json=json, content=content, headers=hdrs) as response:
                if response.is_redirect and method.upper() == "GET":
                    location = response.headers.get("location", "")
                    current = validate_url(urljoin(current, location), allow_http=allow_http)
                    continue
                body = b""
                for chunk in response.iter_bytes():
                    body += chunk
                    if len(body) > max_bytes:
                        raise UnsafeURLError(f"Response exceeds {max_bytes // 1024} KB.")
                return SafeResponse(
                    url=current,
                    status_code=response.status_code,
                    content_type=response.headers.get("content-type", "").split(";")[0].strip().lower(),
                    body=body,
                )
    raise UnsafeURLError("Too many redirects.")
