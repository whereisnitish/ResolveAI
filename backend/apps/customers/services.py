from __future__ import annotations

import hashlib
import secrets
from collections.abc import Iterable
from typing import Any

from django.db import transaction
from django.utils import timezone

from apps.accounts.models import User
from apps.customers.models import Customer, CustomerIdentity, CustomerIdentityKind, CustomerNote
from apps.workspaces.models import Tag, Workspace
from common.exceptions import ServiceError

EDITABLE_FIELDS = ("name", "email", "phone", "attributes")


def hash_visitor_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def resolve_tags(workspace: Workspace, tag_ids: Iterable[Any]) -> list[Tag]:
    """Fetch tags by id, rejecting any that don't belong to ``workspace``."""
    ids = list(dict.fromkeys(str(t) for t in tag_ids))
    tags = list(Tag.objects.filter(workspace=workspace, id__in=ids))
    if len(tags) != len(ids):
        raise ServiceError("One or more tags were not found in this workspace.", code="invalid_tags")
    return tags


@transaction.atomic
def create_customer(*, workspace: Workspace, data: dict[str, Any]) -> Customer:
    fields = {k: v for k, v in data.items() if k in EDITABLE_FIELDS}
    customer = Customer.objects.create(workspace=workspace, identified_at=timezone.now(), **fields)
    if data.get("tag_ids"):
        customer.tags.set(resolve_tags(workspace, data["tag_ids"]))
    return customer


@transaction.atomic
def update_customer(*, customer: Customer, data: dict[str, Any]) -> Customer:
    changed = [k for k in EDITABLE_FIELDS if k in data and getattr(customer, k) != data[k]]
    for key in changed:
        setattr(customer, key, data[key])
    if (
        ("name" in changed or "email" in changed)
        and customer.identified_at is None
        and (customer.name or customer.email)
    ):
        customer.identified_at = timezone.now()
        changed.append("identified_at")
    if changed:
        customer.save(update_fields=[*changed, "updated_at"])
    if "tag_ids" in data:
        customer.tags.set(resolve_tags(customer.workspace, data["tag_ids"]))
    return customer


def add_note(*, customer: Customer, author: User, body: str) -> CustomerNote:
    return CustomerNote.objects.create(workspace=customer.workspace, customer=customer, author=author, body=body)


# -----------------------------------------------------------------------------
# Widget visitors
# -----------------------------------------------------------------------------
@transaction.atomic
def get_or_create_visitor(
    *, workspace: Workspace, raw_token: str | None, page_url: str = "", user_agent: str = ""
) -> tuple[Customer, CustomerIdentity, str]:
    """Resolve a visitor token to a customer, or create a new anonymous visitor.

    Returns (customer, identity, raw_token). The raw token is only ever returned
    to the browser that owns it; the DB stores its hash.
    """
    identity = None
    if raw_token:
        identity = (
            CustomerIdentity.objects.select_related("customer")
            .filter(workspace=workspace, kind=CustomerIdentityKind.VISITOR, value_hash=hash_visitor_token(raw_token))
            .first()
        )
    if identity is None:
        raw_token = secrets.token_urlsafe(32)
        customer = Customer.objects.create(workspace=workspace)
        identity = CustomerIdentity.objects.create(
            workspace=workspace,
            customer=customer,
            kind=CustomerIdentityKind.VISITOR,
            value_hash=hash_visitor_token(raw_token),
        )
    customer = identity.customer
    now = timezone.now()
    customer.last_seen_at = now
    customer.last_seen_url = page_url[:500]
    customer.user_agent = user_agent[:300]
    customer.save(update_fields=["last_seen_at", "last_seen_url", "user_agent", "updated_at"])
    identity.last_used_at = now
    identity.save(update_fields=["last_used_at", "updated_at"])
    assert raw_token is not None
    return customer, identity, raw_token


def identify_visitor(*, customer: Customer, name: str | None, email: str | None) -> Customer:
    """Record a visitor's self-reported name/email on *their own* record only.

    Unverified claims never merge with or reveal other customers (a visitor
    could type anyone's email). Verified identity (HMAC) is a separate flow.
    """
    changed: list[str] = []
    if name is not None and name != customer.name:
        customer.name = name
        changed.append("name")
    if email is not None and email != customer.email:
        customer.email = email
        changed.append("email")
    if changed:
        if customer.identified_at is None:
            customer.identified_at = timezone.now()
            changed.append("identified_at")
        customer.save(update_fields=[*changed, "updated_at"])
    return customer
