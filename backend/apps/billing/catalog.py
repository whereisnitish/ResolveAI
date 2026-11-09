"""Default plan catalog (seeded by migration, editable in Django admin)."""

from __future__ import annotations

from typing import Any

TRIAL_PLAN_CODE = "trial"

PLANS: list[dict[str, Any]] = [
    {
        "code": TRIAL_PLAN_CODE,
        "name": "Free trial",
        "description": "Try ResolveAI free for 14 days.",
        "prices": {"INR": 0, "USD": 0},
        "limits": {"seats": 5, "workspaces": 1, "ai_executions_per_month": 300, "knowledge_mb": 50},
        "features": ["Shared inbox", "Website widget", "AI agent (300 replies)", "50 MB knowledge"],
        "trial_days": 14,
        "is_public": False,
        "is_trial": True,
        "sort_order": 0,
    },
    {
        "code": "starter",
        "name": "Starter",
        "description": "For small teams getting started with AI support.",
        "prices": {"INR": 249900, "USD": 3900},
        "limits": {"seats": 3, "workspaces": 1, "ai_executions_per_month": 1000, "knowledge_mb": 100},
        "features": ["3 seats", "1 workspace", "1,000 AI replies / month", "100 MB knowledge", "Email support"],
        "sort_order": 10,
    },
    {
        "code": "growth",
        "name": "Growth",
        "description": "For growing support teams that automate at scale.",
        "prices": {"INR": 799900, "USD": 9900},
        "limits": {"seats": 10, "workspaces": 3, "ai_executions_per_month": 10000, "knowledge_mb": 1000},
        "features": [
            "10 seats",
            "3 workspaces",
            "10,000 AI replies / month",
            "1 GB knowledge",
            "Workflows & integrations",
        ],
        "sort_order": 20,
    },
    {
        "code": "scale",
        "name": "Scale",
        "description": "For multi-brand companies and agencies.",
        "prices": {"INR": 2499900, "USD": 29900},
        "limits": {"seats": 50, "workspaces": 10, "ai_executions_per_month": 50000, "knowledge_mb": 5000},
        "features": ["50 seats", "10 workspaces", "50,000 AI replies / month", "5 GB knowledge", "Priority support"],
        "sort_order": 30,
    },
]

# Limits applied when a subscription is expired/canceled: the inbox keeps working, AI pauses.
INACTIVE_LIMITS = {"seats": 5, "workspaces": 1, "ai_executions_per_month": 0, "knowledge_mb": 50}
