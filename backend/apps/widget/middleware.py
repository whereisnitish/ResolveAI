"""CORS for the public widget API (/api/v1/widget/).

The widget runs on customer websites, so the set of origins is per-workspace and
unknown at preflight time. CORS here only lets browsers *read* responses; the
real origin authorization happens in the widget views against the workspace's
``allowed_origins``. Credentials (cookies) are never allowed: the widget
authenticates with a bearer token, so dashboard sessions can't be ridden.
"""

from __future__ import annotations

from collections.abc import Callable

from django.http import HttpRequest, HttpResponse

WIDGET_PREFIX = "/api/v1/widget/"
ALLOWED_METHODS = "GET, POST, OPTIONS"
ALLOWED_HEADERS = "authorization, content-type, x-request-id"


class WidgetCorsMiddleware:
    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        if not request.path.startswith(WIDGET_PREFIX):
            return self.get_response(request)

        origin = request.headers.get("Origin")
        if request.method == "OPTIONS" and request.headers.get("Access-Control-Request-Method"):
            response = HttpResponse(status=204)
            response["Access-Control-Allow-Methods"] = ALLOWED_METHODS
            response["Access-Control-Allow-Headers"] = ALLOWED_HEADERS
            response["Access-Control-Max-Age"] = "600"
        else:
            response = self.get_response(request)

        if origin:
            response["Access-Control-Allow-Origin"] = origin
            response["Vary"] = "Origin"
        return response
