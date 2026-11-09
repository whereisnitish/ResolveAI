from __future__ import annotations

from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from django.db import models

from apps.workspaces.models import WorkspaceOwnedModel

SUPPORTED_EVENTS = ["conversation.created", "conversation.resolved", "conversation.assigned", "message.created"]


class IntegrationKind(models.TextChoices):
    WEBHOOK = "webhook", "Outgoing webhook"
    SLACK = "slack", "Slack (incoming webhook)"


class Integration(WorkspaceOwnedModel):
    kind = models.CharField(max_length=20, choices=IntegrationKind.choices)
    name = models.CharField(max_length=80)
    enabled = models.BooleanField(default=True)
    # Secrets are encrypted at rest (common.crypto). Slack webhook URLs are bearer secrets.
    url_encrypted = models.TextField()
    url_host = models.CharField(max_length=255)  # display-only
    signing_secret_encrypted = models.TextField(blank=True, default="")
    events = ArrayField(models.CharField(max_length=60), default=list)
    consecutive_failures = models.PositiveIntegerField(default=0)
    last_delivery_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        ordering = ["name"]


class DeliveryStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    SUCCEEDED = "succeeded", "Succeeded"
    FAILED = "failed", "Failed"


class IntegrationDelivery(WorkspaceOwnedModel):
    integration = models.ForeignKey(Integration, on_delete=models.CASCADE, related_name="deliveries")
    event = models.CharField(max_length=60)
    payload = models.JSONField()
    status = models.CharField(max_length=20, choices=DeliveryStatus.choices, default=DeliveryStatus.PENDING)
    attempts = models.PositiveSmallIntegerField(default=0)
    response_status = models.PositiveSmallIntegerField(null=True, blank=True)
    error = models.CharField(max_length=500, blank=True, default="")
    delivered_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["integration", "-created_at"], name="delivery_integration_created")]
