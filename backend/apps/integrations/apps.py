from django.apps import AppConfig


class IntegrationsConfig(AppConfig):
    name = "apps.integrations"
    label = "integrations"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self) -> None:
        from apps.integrations.tasks import on_event
        from common import events

        for name in ("conversation.created", "message.created", "conversation.status_changed", "conversation.assigned"):
            events.subscribe(name, on_event)
