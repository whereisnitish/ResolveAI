from __future__ import annotations

from django.db import transaction


def queue_email(*, to: str, subject: str, body: str) -> None:
    """Send an email asynchronously once the surrounding transaction commits.

    Deferring to on_commit guarantees we never email about rows that were
    rolled back (e.g. a failed registration).
    """
    from common.tasks import send_email_task

    transaction.on_commit(lambda: send_email_task.delay(to=to, subject=subject, body=body))
