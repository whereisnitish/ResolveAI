from channels.auth import AuthMiddlewareStack
from channels.security.websocket import OriginValidator
from django.conf import settings
from django.urls import path

from apps.realtime.consumers import WidgetConsumer, WorkspaceConsumer

# Dashboard sockets authenticate with the session cookie, which browsers attach
# to cross-site WebSocket handshakes. Restricting Origin to the dashboard
# origins prevents cross-site WebSocket hijacking.
dashboard_socket = OriginValidator(
    AuthMiddlewareStack(WorkspaceConsumer.as_asgi()), list(settings.CSRF_TRUSTED_ORIGINS)
)

websocket_urlpatterns = [
    path("ws/workspaces/<uuid:workspace_id>/", dashboard_socket),
    # Widget sockets authenticate with a session token sent as the first frame
    # (no cookies); origin is checked against the workspace's allowed origins.
    path("ws/widget/", WidgetConsumer.as_asgi()),
]
