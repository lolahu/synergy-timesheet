from collections import defaultdict
from datetime import date, timedelta

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.shortcuts import render
from django.urls import path
from django.utils import timezone
from django.utils.html import format_html

from . import admin_user  # noqa: F401 -- Customize the Admin Site UI
from .models import ParkingEntry, Project, TimeEntry, Worker

User = get_user_model()


def to_monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


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



@admin.register(TimeEntry)
class TimeEntryAdmin(admin.ModelAdmin):
    list_display = ("worker", "project", "work_date", "hours", "status", "entered_by")
    list_filter = ("status", "project", "work_date")
    search_fields = ("worker__display_name", "project__name")

    change_list_template = "admin/core/timeentry/change_list.html"

    def get_urls(self):
        urls = super().get_urls()
        custom = [
            path(
                "weekly-dashboard/",
                self.admin_site.admin_view(self.weekly_dashboard_view),
                name="core_timeentry_weekly_dashboard",
            ),
        ]
        return custom + urls

    def weekly_dashboard_view(self, request):
        """
        Dashboard: total hours by (week_start, worker, project).
        Shows all known worker+project combos even if no entries exist for the selected week.
        """
        week_str = request.GET.get("week")
        project_id = request.GET.get("project_id")
        worker_id = request.GET.get("worker_id")

        # Resolve selected week
        today = timezone.localdate()
        this_monday = to_monday(today)

        if week_str:
            try:
                selected_week = to_monday(date.fromisoformat(week_str))
            except ValueError:
                selected_week = this_monday
        else:
            selected_week = this_monday

        week_end = selected_week + timedelta(days=6)

        # All-time entries — SUBMITTED and APPROVED only (excludes OVERWRITTEN and REJECTED)
        all_qs = TimeEntry.objects.select_related("worker", "project").filter(
            status__in=[TimeEntry.Status.SUBMITTED, TimeEntry.Status.APPROVED]
        )
        if project_id:
            all_qs = all_qs.filter(project_id=project_id)
        if worker_id:
            all_qs = all_qs.filter(worker_id=worker_id)

        # Build: (worker_id, project_id) -> list of (work_date, hours)
        combo_entries = defaultdict(list)
        worker_map = {}
        project_map = {}
        for e in all_qs:
            key = (e.worker_id, e.project_id)
            combo_entries[key].append((e.work_date, float(e.hours)))
            worker_map[e.worker_id] = e.worker
            project_map[e.project_id] = e.project

        rows = []
        for (wid, pid), entries in combo_entries.items():
            # Weekly hours: sum entries that fall within selected week
            weekly_total = sum(
                h for d, h in entries
                if selected_week <= d <= week_end
            )

            # Cumulative hours: all entries up to and including week_end
            cumulative = sum(
                h for d, h in entries
                if d <= week_end
            )

            rows.append({
                "week_start": selected_week,
                "worker": worker_map.get(wid),
                "project": project_map.get(pid),
                "worker_id": wid,
                "project_id": pid,
                "total_hours": round(weekly_total, 2) if weekly_total else "—",
                "cumulative_hours": round(cumulative, 2),
            })

        # Sort by worker name then project name
        rows.sort(key=lambda r: (
            (r["worker"].display_name if r["worker"] else ""),
            (r["project"].name if r["project"] else ""),
        ))

        # Friday display for each row (Mon + 4 days)
        for r in rows:
            r["week_friday"] = r["week_start"] + timedelta(days=4)

        context = dict(
            self.admin_site.each_context(request),
            rows=rows,
            projects=Project.objects.filter(is_active=True).order_by("name"),
            workers=Worker.objects.filter(is_active=True).order_by("display_name"),
            selected_week=selected_week.isoformat(),
            selected_week_friday=(selected_week + timedelta(days=4)).isoformat(),
            selected_project_id=(project_id or ""),
            selected_worker_id=(worker_id or ""),
        )
        return render(request, "admin/core/timeentry/weekly_dashboard.html", context)



@admin.register(ParkingEntry)
class ParkingEntryAdmin(admin.ModelAdmin):
    list_display = ("worker", "project", "work_date", "amount", "status", "submitted_by", "receipt_link", "created_at")
    list_filter = ("status", "project", "work_date")
    search_fields = ("worker__display_name", "project__name")
    readonly_fields = ("receipt_preview",)

    def receipt_link(self, obj):
        if obj.receipt:
            return format_html(
                '<a href="{}" target="_blank" rel="noopener noreferrer">📎 View</a>',
                obj.receipt.url,
            )
        return "—"
    receipt_link.short_description = "Receipt"

    def receipt_preview(self, obj):
        if obj.receipt:
            url = obj.receipt.url
            name = obj.receipt.name.lower()
            if name.endswith(".pdf"):
                return format_html(
                    '<a href="{}" target="_blank" rel="noopener noreferrer">'
                    '📄 Open PDF in new tab</a>',
                    url,
                )
            else:
                return format_html(
                    '<a href="{}" target="_blank" rel="noopener noreferrer">'
                    '<img src="{}" style="max-width: 400px; max-height: 400px; '
                    'border: 1px solid #ccc; border-radius: 4px;" />'
                    '</a>',
                    url, url,
                )
        return "No receipt uploaded."
    receipt_preview.short_description = "Receipt Preview"

    fieldsets = (
        ("Submission", {"fields": ("worker", "project", "work_date", "amount", "notes")}),
        ("Receipt", {"fields": ("receipt", "receipt_preview")}),
        ("Status", {"fields": ("status", "reviewed_by", "reviewed_at", "review_notes")}),
        ("Meta", {"fields": ("submitted_by",)}),
    )

admin.site.unregister(User)

@admin.register(User)
class UserAdmin(BaseUserAdmin):
    """
    Extends the default UserAdmin to show pending signups prominently
    and provide a one-click approve action that also activates the Worker profile.
    Username field is hidden — email is used as the login identifier.
    """
    list_display = ("email", "full_name", "is_active", "is_staff", "account_status", "date_joined")
    list_filter = ("is_active", "is_staff", "date_joined")
    search_fields = ("email", "first_name", "last_name")
    ordering = ("is_active", "-date_joined")  # pending (inactive) shown first
    actions = ["approve_accounts", "deactivate_accounts"]

    # Remove username from the add/change forms — email is used instead
    add_fieldsets = (
        (None, {
            "classes": ("wide",),
            "fields": ("email", "first_name", "last_name", "password1", "password2", "is_active", "is_staff"),
        }),
    )
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Personal info", {"fields": ("first_name", "last_name")}),
        ("Permissions", {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")}),
        ("Important dates", {"fields": ("last_login", "date_joined")}),
    )

    def save_model(self, request, obj, form, change):
        # Always keep username in sync with email
        obj.username = obj.email
        super().save_model(request, obj, form, change)

        # Auto-create or sync Worker profile
        if obj.email:
            Worker.objects.get_or_create(
                email=obj.email,
                defaults={
                    "display_name": obj.get_full_name() or obj.email.split("@")[0],
                    "is_active": obj.is_active,
                    "user": obj,
                },
            )

    def full_name(self, obj):
        return obj.get_full_name() or "—"
    full_name.short_description = "Name"

    def account_status(self, obj):
        from django.utils.safestring import mark_safe
        if not obj.is_active:
            return mark_safe('<span style="color: #c0392b; font-weight: bold;">Pending Approval</span>')
        elif obj.is_staff:
            return mark_safe('<span style="color: #417690;">Admin</span>')
        else:
            return mark_safe('<span style="color: #27ae60;">Active</span>')
    account_status.short_description = "Status"

    @admin.action(description="Approve selected accounts")
    def approve_accounts(self, request, queryset):
        count = 0
        for user in queryset.filter(is_active=False):
            user.is_active = True
            user.save(update_fields=["is_active"])
            Worker.objects.filter(email=user.email, is_active=False).update(is_active=True)
            count += 1
        self.message_user(request, f"Approved {count} account(s). Workers have been activated.")

    @admin.action(description="Deactivate selected accounts")
    def deactivate_accounts(self, request, queryset):
        count = queryset.filter(is_active=True).update(is_active=False)
        self.message_user(request, f"Deactivated {count} account(s).")