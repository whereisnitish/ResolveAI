from django.apps import AppConfig


class CommonConfig(AppConfig):
    name = "common"
    verbose_name = "Common"

    def ready(self) -> None:
        from common import checks, schema  # noqa: F401  (registers deploy checks + OpenAPI extensions)
