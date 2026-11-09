from django.urls import include, path

from apps.billing.api import BillingWebhookView, PlanListView
from apps.organizations.urls import invitation_urlpatterns
from common.views import HealthView, LivenessView

urlpatterns = [
    path("health/", HealthView.as_view(), name="health"),
    path("health/live/", LivenessView.as_view(), name="health-live"),
    path("health/ready/", HealthView.as_view(), name="health-ready"),
    path("auth/", include("apps.accounts.urls")),
    path("organizations/", include("apps.organizations.urls")),
    path("invitations/", include((invitation_urlpatterns, "invitations"))),
    path("workspaces/", include("apps.workspaces.urls")),
    path("widget/", include("apps.widget.urls")),
    path("billing/plans/", PlanListView.as_view(), name="billing-plans"),
    path("billing/webhooks/<str:provider>/", BillingWebhookView.as_view(), name="billing-webhook"),
]
