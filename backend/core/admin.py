from collections import defaultdict
from datetime import date, timedelta

from django.contrib import admin
from django.shortcuts import render
from django.urls import path
from django.utils import timezone

from . import admin_user  # noqa: F401 -- Customize the Admin Site UI
from .models import AccessRequest, MagicLinkToken, Project, RateOverride, TimeEntry, Worker


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


@admin.register(RateOverride)
class RateOverrideAdmin(admin.ModelAdmin):
    list_display = ("worker", "project", "hourly_rate", "effective_from", "effective_to")
    list_filter = ("project", "worker")


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

        # All-time entries — only SUBMITTED (excludes OVERWRITTEN and REJECTED)
        all_qs = TimeEntry.objects.select_related("worker", "project").filter(
            status=TimeEntry.Status.SUBMITTED
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


@admin.register(AccessRequest)
class AccessRequestAdmin(admin.ModelAdmin):
    list_display = ("email", "status", "requested_at", "reviewed_by", "reviewed_at")
    list_filter = ("status",)
    search_fields = ("email", "requested_name")

    actions = ["approve_and_create_worker"]

    def _ensure_worker_for_request(self, req: AccessRequest) -> Worker:
        email = (req.email or "").strip().lower()

        worker = Worker.objects.filter(email=email).first()
        if worker:
            if not worker.is_active:
                worker.is_active = True
                worker.save(update_fields=["is_active"])
            return worker

        display_name = (req.requested_name or "").strip()
        if not display_name:
            display_name = email.split("@")[0] if "@" in email else email

        worker = Worker.objects.create(
            display_name=display_name,
            email=email,
            is_active=True,
        )
        return worker

    def save_model(self, request, obj, form, change):
        previous_status = None
        if change and obj.pk:
            previous_status = AccessRequest.objects.filter(pk=obj.pk).values_list("status", flat=True).first()

        obj.email = (obj.email or "").strip().lower()

        is_becoming_approved = (obj.status == AccessRequest.Status.APPROVED) and (previous_status != AccessRequest.Status.APPROVED)

        if is_becoming_approved:
            if not obj.reviewed_by:
                obj.reviewed_by = request.user
            if not obj.reviewed_at:
                obj.reviewed_at = timezone.now()

        super().save_model(request, obj, form, change)

        if is_becoming_approved:
            self._ensure_worker_for_request(obj)

    @admin.action(description="Approve selected requests and auto-create Workers")
    def approve_and_create_worker(self, request, queryset):
        now = timezone.now()
        for req in queryset:
            req.email = (req.email or "").strip().lower()
            req.status = AccessRequest.Status.APPROVED
            req.reviewed_by = request.user
            req.reviewed_at = now
            req.save()
            self._ensure_worker_for_request(req)
        self.message_user(request, f"Approved {queryset.count()} request(s) and ensured Worker records exist.")


@admin.register(MagicLinkToken)
class MagicLinkTokenAdmin(admin.ModelAdmin):
    list_display = ("user", "expires_at", "used_at", "created_at")
    list_filter = ("used_at",)
    search_fields = ("user__email",)