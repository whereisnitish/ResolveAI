"""Shared test helpers for Phase 3/4."""

from __future__ import annotations

import uuid
from typing import Any

from apps.billing.models import Subscription
from apps.billing.usage import get_plan


def make_pdf(text: str) -> bytes:
    """Build a tiny valid single-page PDF containing `text` (with a correct xref table)."""
    stream = f"BT /F1 18 Tf 72 700 Td ({text}) Tj ET".encode()
    objects = [
        b"<</Type/Catalog/Pages 2 0 R>>",
        b"<</Type/Pages/Kids[3 0 R]/Count 1>>",
        b"<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]/Contents 4 0 R/Resources<</Font<</F1 5 0 R>>>>>>",
        b"<</Length " + str(len(stream)).encode() + b">>stream\n" + stream + b"\nendstream",
        b"<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for n, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{n} 0 obj".encode() + body + b"endobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += f"trailer<</Size {len(objects) + 1}/Root 1 0 R>>\nstartxref\n{xref}\n%%EOF".encode()
    return bytes(out)


def set_plan(org: Any, code: str = "scale", status: str = "active", **limit_overrides: int) -> Subscription:
    """Put an organization on a plan, optionally overriding limits via a private plan copy."""
    plan = get_plan(code)
    if limit_overrides:
        plan.pk = None
        plan.id = None
        plan.code = f"{code}-test-{uuid.uuid4().hex[:10]}"
        plan.is_public = False
        plan.limits = {**plan.limits, **limit_overrides}
        plan.save()
    sub, _ = Subscription.objects.update_or_create(organization=org, defaults={"plan": plan, "status": status})
    return sub
