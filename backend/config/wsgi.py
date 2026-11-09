from config.env import configure_settings_module

configure_settings_module()

from django.core.wsgi import get_wsgi_application  # noqa: E402

application = get_wsgi_application()
