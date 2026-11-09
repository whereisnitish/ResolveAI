from __future__ import annotations

from typing import Any

from django.db import models

from common.models import BaseModel, UUIDModel


class Metric(models.TextChoices):
    AI_EXECUTIONS = "ai_executions", "AI executions"
    AI_CONVERSATIONS = "ai_conversations", "AI conversations"
    AI_INPUT_TOKENS = "ai_input_tokens", "AI input tokens"
    AI_OUTPUT_TOKENS = "ai_output_tokens", "AI output tokens"
    EMBEDDING_TOKENS = "embedding_tokens", "Embedding tokens"


class Plan(BaseModel):
    """A sellable plan. Prices are in minor units (paise / cents) per currency.

    limits keys: seats, workspaces, ai_executions_per_month, knowledge_mb.
    provider_prices: {"stripe": {"USD": "price_..."}, "razorpay": {"INR": "plan_..."}}
    """

    code = models.SlugField(max_length=40, unique=True)
    name = models.CharField(max_length=80)
    description = models.CharField(max_length=255, blank=True, default="")
    prices = models.JSONField(default=dict)
    limits = models.JSONField(default=dict)
    features = models.JSONField(default=list, blank=True)
    provider_prices = models.JSONField(default=dict, blank=True)
    trial_days = models.PositiveIntegerField(default=0)
    is_public = models.BooleanField(default=True)
    is_trial = models.BooleanField(default=False)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["sort_order"]

    def __str__(self) -> str:
        return self.name

    def limit(self, key: str) -> int:
        return int(self.limits.get(key, 0))


class SubscriptionStatus(models.TextChoices):
    TRIALING = "trialing", "Trialing"
    ACTIVE = "active", "Active"
    PAST_DUE = "past_due", "Past due"
    CANCELED = "canceled", "Canceled"
    EXPIRED = "expired", "Trial expired"


class PaymentProviderName(models.TextChoices):
    NONE = "", "None"
    STRIPE = "stripe", "Stripe"
    RAZORPAY = "razorpay", "Razorpay"
    MOCK = "mock", "Mock (development)"


class Subscription(BaseModel):
    organization = models.OneToOneField(
        "organizations.Organization", on_delete=models.CASCADE, related_name="subscription"
    )
    plan = models.ForeignKey(Plan, on_delete=models.PROTECT, related_name="subscriptions")
    status = models.CharField(max_length=20, choices=SubscriptionStatus.choices)
    provider = models.CharField(max_length=20, choices=PaymentProviderName.choices, blank=True, default="")
    provider_customer_id = models.CharField(max_length=120, blank=True, default="")
    provider_subscription_id = models.CharField(max_length=120, blank=True, default="", db_index=True)
    currency = models.CharField(max_length=3, blank=True, default="")
    current_period_start = models.DateTimeField(null=True, blank=True)
    current_period_end = models.DateTimeField(null=True, blank=True)
    trial_ends_at = models.DateTimeField(null=True, blank=True)
    cancel_at_period_end = models.BooleanField(default=False)

    def __str__(self) -> str:
        return f"{self.organization_id}: {self.plan.code} ({self.status})"


class UsageLedger(UUIDModel):
    """Append-only metering ledger. Quantities are only ever computed server-side.

    `idempotency_key` makes recording safe to retry (e.g. Celery retries).
    """

    organization = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="+")
    workspace_id = models.UUIDField(null=True, blank=True)
    metric = models.CharField(max_length=40, choices=Metric.choices)
    quantity = models.BigIntegerField()
    idempotency_key = models.CharField(max_length=200, unique=True)
    source_type = models.CharField(max_length=60, blank=True, default="")
    source_id = models.CharField(max_length=64, blank=True, default="")
    occurred_at = models.DateTimeField(db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-occurred_at"]
        indexes = [models.Index(fields=["organization", "metric", "occurred_at"], name="usage_org_metric_time")]
        constraints = [models.CheckConstraint(condition=models.Q(quantity__gte=0), name="usage_quantity_non_negative")]

    def save(self, *args: Any, **kwargs: Any) -> None:
        if not self._state.adding:
            raise RuntimeError("UsageLedger entries are append-only")
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("UsageLedger entries are append-only")


class InvoiceStatus(models.TextChoices):
    PAID = "paid", "Paid"
    OPEN = "open", "Open"
    FAILED = "failed", "Payment failed"
    VOID = "void", "Void"


class Invoice(BaseModel):
    organization = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="invoices")
    provider = models.CharField(max_length=20, choices=PaymentProviderName.choices)
    provider_invoice_id = models.CharField(max_length=120)
    amount_minor = models.BigIntegerField()
    currency = models.CharField(max_length=3)
    status = models.CharField(max_length=20, choices=InvoiceStatus.choices)
    hosted_url = models.URLField(max_length=500, blank=True, default="")
    period_start = models.DateTimeField(null=True, blank=True)
    period_end = models.DateTimeField(null=True, blank=True)
    issued_at = models.DateTimeField()

    class Meta:
        ordering = ["-issued_at"]
        constraints = [
            models.UniqueConstraint(fields=["provider", "provider_invoice_id"], name="invoice_unique_provider_id"),
        ]


class WebhookStatus(models.TextChoices):
    RECEIVED = "received", "Received"
    PROCESSED = "processed", "Processed"
    IGNORED = "ignored", "Ignored"
    FAILED = "failed", "Failed"


class WebhookEvent(BaseModel):
    """Every verified provider webhook. Unique (provider, event_id) makes processing idempotent."""

    provider = models.CharField(max_length=20, choices=PaymentProviderName.choices)
    event_id = models.CharField(max_length=200)
    event_type = models.CharField(max_length=100)
    payload = models.JSONField()
    status = models.CharField(max_length=20, choices=WebhookStatus.choices, default=WebhookStatus.RECEIVED)
    error = models.TextField(blank=True, default="")
    attempts = models.PositiveIntegerField(default=0)
    processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [models.UniqueConstraint(fields=["provider", "event_id"], name="webhook_event_unique")]
