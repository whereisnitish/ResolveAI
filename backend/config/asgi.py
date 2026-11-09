"""ASGI entrypoint: HTTP via Django, WebSockets via Channels.

WebSocket routes (inbox real-time updates, widget messaging) are registered in
apps/realtime/routing.py.
"""

from config.env import configure_settings_module

configure_settings_module()

from django.core.asgi import get_asgi_application  # noqa: E402

django_asgi_app = get_asgi_application()

from channels.routing import ProtocolTypeRouter, URLRouter  # noqa: E402

from config.routing import websocket_urlpatterns  # noqa: E402

application = ProtocolTypeRouter(
    {
        "http": django_asgi_app,
        # Per-route auth and origin policies live in apps/realtime/routing.py.
        "websocket": URLRouter(websocket_urlpatterns),
    }
)
