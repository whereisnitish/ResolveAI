from drf_spectacular.extensions import OpenApiAuthenticationExtension


class SessionCookieScheme(OpenApiAuthenticationExtension):
    target_class = "common.authentication.CsrfEnforcedSessionAuthentication"
    name = "sessionCookie"

    def get_security_definition(self, auto_schema):  # type: ignore[no-untyped-def]
        return {"type": "apiKey", "in": "cookie", "name": "resolveai_session"}


class WidgetBearerScheme(OpenApiAuthenticationExtension):
    target_class = "apps.widget.auth.WidgetTokenAuthentication"
    name = "widgetSession"

    def get_security_definition(self, auto_schema):  # type: ignore[no-untyped-def]
        return {
            "type": "http",
            "scheme": "bearer",
            "description": "Short-lived widget session token from POST /api/v1/widget/session/.",
        }
