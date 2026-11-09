from django.urls import path

from apps.widget import views

app_name = "widget"

urlpatterns = [
    path("session/", views.WidgetSessionView.as_view(), name="session"),
    path("identify/", views.WidgetIdentifyView.as_view(), name="identify"),
    path("conversations/", views.WidgetConversationsView.as_view(), name="conversations"),
    path("conversations/<uuid:conversation_id>/messages/", views.WidgetMessagesView.as_view(), name="messages"),
    path("attachments/<uuid:attachment_id>/", views.WidgetAttachmentView.as_view(), name="attachment"),
]
