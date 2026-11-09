from __future__ import annotations

from typing import Any

from django.conf import settings
from django.db import models

from common.models import UUIDModel


class AuditLog(UUIDModel):
    """Append-only record of security-sensitive actions.

    Tenant references are stored as plain UUIDs (not FKs) so that the trail
    survives deletion of the organization/workspace it describes.
    """

    organization_id = models.UUIDField(null=True, blank=True, db_index=True)
    workspace_id = models.UUIDField(null=True, blank=True, db_index=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    actor_email = models.EmailField(blank=True, default="")
    action = models.CharField(max_length=80, db_index=True)
    target_type = models.CharField(max_length=80, blank=True, default="")
    target_id = models.CharField(max_length=64, blank=True, default="")
    metadata = models.JSONField(default=dict, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=512, blank=True, default="")
    request_id = models.CharField(max_length=64, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["organization_id", "-created_at"], name="audit_org_created"),
        ]

    def __str__(self) -> str:
        return f"{self.action} by {self.actor_email or 'system'}"

    def save(self, *args: Any, **kwargs: Any) -> None:
        if not self._state.adding:
            raise RuntimeError("AuditLog entries are append-only")
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("AuditLog entries are append-only")
