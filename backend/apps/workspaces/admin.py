from django.contrib import admin

from apps.workspaces.models import Workspace, WorkspaceMembership


class WorkspaceMembershipInline(admin.TabularInline):
    model = WorkspaceMembership
    extra = 0
    raw_id_fields = ["user"]


@admin.register(Workspace)
class WorkspaceAdmin(admin.ModelAdmin):
    list_display = ["name", "organization", "slug", "public_id", "is_default", "archived_at"]
    search_fields = ["name", "slug", "public_id"]
    raw_id_fields = ["organization"]
    inlines = [WorkspaceMembershipInline]
