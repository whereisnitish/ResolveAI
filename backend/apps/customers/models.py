from __future__ import annotations

from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.workspaces.models import Tag, WorkspaceOwnedModel


class Customer(WorkspaceOwnedModel):
    """An end customer / website visitor of a workspace. Never a platform User.

    Anonymous visitors are customers with ``identified_at`` = NULL. A visitor
    can *claim* a name/email via the widget, but that never merges them with
    another customer record: unverified claims are only stored on their own
    record (see docs/decisions/0006-widget-auth-and-identity.md).
    """

    name = models.CharField(max_length=150, blank=True, default="")
    # Contact email. Not unique: unverified claims from different visitors may collide.
    email = models.EmailField(max_length=254, blank=True, default="")
    phone = models.CharField(max_length=32, blank=True, default="")
    # Reserved for verified identity (customer's own user id, HMAC-verified). Unique per workspace.
    external_id = models.CharField(max_length=128, blank=True, default="")
    attributes = models.JSONField(default=dict, blank=True)
    tags = models.ManyToManyField(Tag, related_name="customers", blank=True)
    identified_at = models.DateTimeField(null=True, blank=True)
    last_seen_at = models.DateTimeField(null=True, blank=True)
    last_seen_url = models.CharField(max_length=500, blank=True, default="")
    user_agent = models.CharField(max_length=300, blank=True, default="")

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["workspace", "email"], name="customer_ws_email"),
            models.Index(fields=["workspace", "-last_seen_at"], name="customer_ws_last_seen"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["workspace", "external_id"],
                condition=~Q(external_id=""),
                name="customer_unique_external_id_per_workspace",
            ),
        ]

    def __str__(self) -> str:
        return self.display_name

    @property
    def is_anonymous(self) -> bool:
        return self.identified_at is None

    @property
    def display_name(self) -> str:
        return self.name or self.email or f"Visitor {str(self.id)[:6]}"


class CustomerIdentityKind(models.TextChoices):
    VISITOR = "visitor", "Widget visitor"


class CustomerIdentity(WorkspaceOwnedModel):
    """A credential that resolves to a customer, e.g. the widget visitor token.

    Only the SHA-256 of the token is stored. Possession of the raw token is what
    lets a browser read that visitor's conversations, so it is treated as a secret.
    """

    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name="identities")
    kind = models.CharField(max_length=20, choices=CustomerIdentityKind.choices)
    value_hash = models.CharField(max_length=64)
    last_used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["workspace", "kind", "value_hash"], name="customer_identity_unique"),
        ]


class CustomerNote(WorkspaceOwnedModel):
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name="notes")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    body = models.TextField(max_length=5000)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["customer", "-created_at"], name="customer_note_customer_created")]
