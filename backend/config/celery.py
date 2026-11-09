import logging

from celery import Celery
from celery.signals import task_failure, task_retry

from config.env import configure_settings_module

configure_settings_module()

app = Celery("resolveai")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()

logger = logging.getLogger("resolveai.tasks")


@task_failure.connect
def _log_task_failure(sender=None, task_id=None, exception=None, **kwargs):  # type: ignore[no-untyped-def]
    # Args are deliberately not logged: they can carry customer content.
    logger.error(
        "task_failed",
        extra={"task": getattr(sender, "name", "?"), "task_id": task_id, "error": type(exception).__name__},
        exc_info=(type(exception), exception, exception.__traceback__) if exception else None,
    )


@task_retry.connect
def _log_task_retry(sender=None, request=None, reason=None, **kwargs):  # type: ignore[no-untyped-def]
    logger.warning(
        "task_retry",
        extra={
            "task": getattr(sender, "name", "?"),
            "task_id": getattr(request, "id", None),
            "reason": str(reason)[:200],
        },
    )
