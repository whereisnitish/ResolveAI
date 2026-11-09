from __future__ import annotations

from django.contrib.postgres.fields import ArrayField
from django.db import models

from common.models import BaseModel


class LauncherPosition(models.TextChoices):
    RIGHT = "right", "Bottom right"
    LEFT = "left", "Bottom left"


class WidgetSettings(BaseModel):
    """Per-workspace configuration of the embeddable chat widget.

    Only the fields in ``PUBLIC_FIELDS`` are ever sent to website visitors.
    """

    workspace = models.OneToOneField("workspaces.Workspace", on_delete=models.CASCADE, related_name="widget_settings")
    enabled = models.BooleanField(default=True)
    # Exact origins (scheme://host[:port]) allowed to embed the widget. Empty = any origin.
    allowed_origins = ArrayField(models.CharField(max_length=255), default=list, blank=True)
    brand_color = models.CharField(max_length=7, default="#4f46e5")
    team_name = models.CharField(max_length=80, blank=True, default="")
    welcome_message = models.CharField(max_length=300, default="Hi there 👋 How can we help you today?")
    launcher_position = models.CharField(
        max_length=10, choices=LauncherPosition.choices, default=LauncherPosition.RIGHT
    )
    collect_email = models.BooleanField(default=True)

    PUBLIC_FIELDS = ("brand_color", "team_name", "welcome_message", "launcher_position", "collect_email")

    def __str__(self) -> str:
        return f"WidgetSettings({self.workspace_id})"

    def origin_allowed(self, origin: str | None) -> bool:
        if not self.allowed_origins:
            return True
        return bool(origin) and origin.rstrip("/").lower() in {o.rstrip("/").lower() for o in self.allowed_origins}
