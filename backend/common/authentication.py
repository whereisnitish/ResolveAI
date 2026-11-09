from __future__ import annotations

from typing import Any

from rest_framework.authentication import CSRFCheck, SessionAuthentication
from rest_framework.exceptions import PermissionDenied
from rest_framework.request import Request


class CsrfEnforcedSessionAuthentication(SessionAuthentication):
    """Session (HttpOnly cookie) auth for the dashboard.

    DRF's SessionAuthentication enforces CSRF for authenticated requests.
    This subclass is the project-owned extension point for the auth strategy.
    """


def enforce_csrf(request: Request) -> None:
    """Enforce CSRF for unauthenticated, state-changing endpoints (login, register...).

    DRF skips CSRF checks for anonymous requests, which would allow login-CSRF
    (an attacker silently signing a victim into the attacker's account).
    """

    def _noop(_request: Any) -> None:
        return None

    check = CSRFCheck(_noop)
    check.process_request(request._request)
    reason = check.process_view(request._request, None, (), {})
    if reason:
        raise PermissionDenied(f"CSRF Failed: {reason}")


class CsrfProtectedAPIViewMixin:
    """Apply CSRF validation to every unsafe request, authenticated or not."""

    def initial(self, request: Request, *args: Any, **kwargs: Any) -> None:
        super().initial(request, *args, **kwargs)  # type: ignore[misc]
        if request.method not in ("GET", "HEAD", "OPTIONS", "TRACE"):
            enforce_csrf(request)
