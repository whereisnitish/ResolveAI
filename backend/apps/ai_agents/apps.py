from django.apps import AppConfig


class AiAgentsConfig(AppConfig):
    name = "apps.ai_agents"
    label = "ai_agents"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self) -> None:
        from apps.ai_agents.tasks import on_message_created
        from common import events

        events.subscribe("message.created", on_message_created)
