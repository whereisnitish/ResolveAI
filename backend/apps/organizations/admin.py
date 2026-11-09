from django.contrib import admin

from apps.organizations.models import Invitation, Organization, OrganizationMembership


class MembershipInline(admin.TabularInline):
    model = OrganizationMembership
    extra = 0
    raw_id_fields = ["user", "invited_by"]


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ["name", "slug", "country", "created_at"]
    search_fields = ["name", "slug"]
    inlines = [MembershipInline]


@admin.register(Invitation)
class InvitationAdmin(admin.ModelAdmin):
    list_display = ["email", "organization", "role", "status", "expires_at"]
    list_filter = ["status", "role"]
    search_fields = ["email"]
    exclude = ["token_hash"]
    raw_id_fields = ["organization", "workspace", "invited_by", "accepted_by"]
