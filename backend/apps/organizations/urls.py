from django.urls import path

from apps.analytics.api import OrganizationAnalyticsView
from apps.billing.api import CheckoutView, InvoiceListView, OrganizationBillingView
from apps.organizations import views
from apps.workspaces.views import OrganizationWorkspaceCreateView

app_name = "organizations"

urlpatterns = [
    path("", views.OrganizationListCreateView.as_view(), name="list"),
    path("<uuid:organization_id>/", views.OrganizationDetailView.as_view(), name="detail"),
    path("<uuid:organization_id>/members/", views.OrganizationMemberListView.as_view(), name="members"),
    path(
        "<uuid:organization_id>/members/<uuid:membership_id>/",
        views.OrganizationMemberDetailView.as_view(),
        name="member-detail",
    ),
    path("<uuid:organization_id>/invitations/", views.InvitationListCreateView.as_view(), name="invitations"),
    path(
        "<uuid:organization_id>/invitations/<uuid:invitation_id>/revoke/",
        views.InvitationRevokeView.as_view(),
        name="invitation-revoke",
    ),
    path("<uuid:organization_id>/workspaces/", OrganizationWorkspaceCreateView.as_view(), name="workspaces"),
    path("<uuid:organization_id>/audit-logs/", views.AuditLogListView.as_view(), name="audit-logs"),
    path("<uuid:organization_id>/billing/", OrganizationBillingView.as_view(), name="billing"),
    path("<uuid:organization_id>/billing/checkout/", CheckoutView.as_view(), name="billing-checkout"),
    path("<uuid:organization_id>/billing/invoices/", InvoiceListView.as_view(), name="billing-invoices"),
    path("<uuid:organization_id>/analytics/", OrganizationAnalyticsView.as_view(), name="analytics"),
]

invitation_urlpatterns = [
    path("preview/", views.InvitationPreviewView.as_view(), name="invitation-preview"),
    path("accept/", views.InvitationAcceptView.as_view(), name="invitation-accept"),
]
