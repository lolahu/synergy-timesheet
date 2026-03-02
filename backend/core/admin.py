from django.contrib import admin
from .models import Worker, Project, RateOverride, TimeEntry, AccessRequest, MagicLinkToken


@admin.register(Worker)
class WorkerAdmin(admin.ModelAdmin):
    list_display = ("display_name", "email", "is_active", "created_at")
    search_fields = ("display_name", "email")
    list_filter = ("is_active",)


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "is_active", "created_at")
    search_fields = ("name", "code")
    list_filter = ("is_active",)


@admin.register(RateOverride)
class RateOverrideAdmin(admin.ModelAdmin):
    list_display = ("worker", "project", "hourly_rate", "effective_from", "effective_to")
    list_filter = ("project", "worker")


@admin.register(TimeEntry)
class TimeEntryAdmin(admin.ModelAdmin):
    list_display = ("worker", "project", "work_date", "hours", "status", "entered_by")
    list_filter = ("status", "project", "work_date")
    search_fields = ("worker__display_name", "project__name")

from .models import AccessRequest, MagicLinkToken

@admin.register(AccessRequest)
class AccessRequestAdmin(admin.ModelAdmin):
    list_display = ("email", "status", "requested_at", "reviewed_by", "reviewed_at")
    list_filter = ("status",)
    search_fields = ("email", "requested_name")

@admin.register(MagicLinkToken)
class MagicLinkTokenAdmin(admin.ModelAdmin):
    list_display = ("user", "expires_at", "used_at", "created_at")
    list_filter = ("used_at",)
    search_fields = ("user__email",)