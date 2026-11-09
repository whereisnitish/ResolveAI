from django.apps import AppConfig


class WorkflowsConfig(AppConfig):
    name = "apps.workflows"
    label = "workflows"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self) -> None:
        from apps.workflows.tasks import on_event
        from common import events

        for name in ("conversation.created", "message.created", "conversation.status_changed"):
            events.subscribe(name, on_event)
