"""Consistent error envelope for every API error.

Shape:
    {"error": {"code": "validation_error", "message": "...", "details": {...}, "request_id": "..."}}

Unexpected exceptions are logged with the request ID and returned as a
generic 500 without internal details.
"""

from __future__ import annotations

import logging
from typing import Any

from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.http import Http404
from rest_framework import exceptions, status
from rest_framework.response import Response
from rest_framework.views import exception_handler

from common.middleware import get_request_id

logger = logging.getLogger(__name__)


class ServiceError(exceptions.APIException):
    """Raised by the service layer for business-rule violations."""

    status_code = status.HTTP_400_BAD_REQUEST
    default_code = "service_error"
    default_detail = "The request could not be completed."

    def __init__(self, message: str | None = None, code: str | None = None, status_code: int | None = None) -> None:
        super().__init__(detail=message or self.default_detail, code=code or self.default_code)
        if status_code is not None:
            self.status_code = status_code


class ConflictError(ServiceError):
    status_code = status.HTTP_409_CONFLICT
    default_code = "conflict"
    default_detail = "The resource is in a conflicting state."


def _error_code(exc: exceptions.APIException) -> str:
    codes = exc.get_codes()
    if isinstance(exc, exceptions.ValidationError):
        return "validation_error"
    if isinstance(codes, str):
        return codes
    return getattr(exc, "default_code", "error")


def api_exception_handler(exc: Exception, context: dict[str, Any]) -> Response | None:
    if isinstance(exc, Http404):
        exc = exceptions.NotFound()
    elif isinstance(exc, DjangoPermissionDenied):
        exc = exceptions.PermissionDenied()

    response = exception_handler(exc, context)
    if response is None:
        logger.exception("Unhandled API exception", exc_info=exc)
        return Response(
            {
                "error": {
                    "code": "server_error",
                    "message": "An unexpected error occurred.",
                    "details": None,
                    "request_id": get_request_id(),
                }
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    assert isinstance(exc, exceptions.APIException)
    if isinstance(exc, exceptions.ValidationError):
        message = "Invalid input."
        details: Any = response.data
    else:
        message = str(exc.detail) if not isinstance(exc.detail, (list, dict)) else "Request failed."
        details = None if not isinstance(exc.detail, (list, dict)) else exc.detail

    response.data = {
        "error": {
            "code": _error_code(exc),
            "message": message,
            "details": details,
            "request_id": get_request_id(),
        }
    }
    return response
