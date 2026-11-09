from django.urls import include, path
from rest_framework.routers import SimpleRouter

from apps.ai_agents.api import AIAgentViewSet, ConversationAIView, WorkspaceExecutionListView
from apps.analytics.api import WorkspaceAnalyticsView
from apps.conversations.views import AssigneeListView, AttachmentDownloadView, ConversationViewSet
from apps.customers.views import CustomerNoteDetailViewSet, CustomerViewSet
from apps.integrations.api import IntegrationViewSet
from apps.knowledge.api import KnowledgeSearchView, KnowledgeSourceViewSet
from apps.widget.views import WidgetSettingsView
from apps.workflows.api import WorkflowViewSet
from apps.workspaces import views
from apps.workspaces.catalog import TagViewSet, TeamViewSet

app_name = "workspaces"

# Workspace-scoped resources: /api/v1/workspaces/<workspace_id>/<resource>/
scoped = SimpleRouter(use_regex_path=False)
scoped.register("customers", CustomerViewSet, basename="customer")
scoped.register("customer-notes", CustomerNoteDetailViewSet, basename="customer-note")
scoped.register("conversations", ConversationViewSet, basename="conversation")
scoped.register("tags", TagViewSet, basename="tag")
scoped.register("teams", TeamViewSet, basename="team")
scoped.register("knowledge/sources", KnowledgeSourceViewSet, basename="knowledge-source")
scoped.register("ai-agents", AIAgentViewSet, basename="ai-agent")
scoped.register("workflows", WorkflowViewSet, basename="workflow")
scoped.register("integrations", IntegrationViewSet, basename="integration")

urlpatterns = [
    path("", views.WorkspaceListView.as_view(), name="list"),
    path("<uuid:workspace_id>/", views.WorkspaceDetailView.as_view(), name="detail"),
    path("<uuid:workspace_id>/members/", views.WorkspaceMemberListCreateView.as_view(), name="members"),
    path(
        "<uuid:workspace_id>/members/<uuid:membership_id>/",
        views.WorkspaceMemberDetailView.as_view(),
        name="member-detail",
    ),
    path("<uuid:workspace_id>/assignees/", AssigneeListView.as_view(), name="assignees"),
    path(
        "<uuid:workspace_id>/attachments/<uuid:attachment_id>/download/",
        AttachmentDownloadView.as_view(),
        name="attachment-download",
    ),
    path("<uuid:workspace_id>/widget-settings/", WidgetSettingsView.as_view(), name="widget-settings"),
    path("<uuid:workspace_id>/knowledge/search/", KnowledgeSearchView.as_view(), name="knowledge-search"),
    path("<uuid:workspace_id>/ai-executions/", WorkspaceExecutionListView.as_view(), name="ai-executions"),
    path(
        "<uuid:workspace_id>/conversations/<uuid:conversation_id>/ai/<str:operation>/",
        ConversationAIView.as_view(),
        name="conversation-ai",
    ),
    path("<uuid:workspace_id>/analytics/", WorkspaceAnalyticsView.as_view(), name="analytics"),
    path("<uuid:workspace_id>/", include(scoped.urls)),
]
