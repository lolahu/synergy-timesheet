from django.contrib import admin
from .models import Worker, Project, RateOverride, TimeEntry, AccessRequest, MagicLinkToken, AccessRequest, Worker, MagicLinkToken
from .models import AccessRequest, MagicLinkToken
from django.utils import timezone
from . import admin_user  # noqa: F401 -- Customize the Admin Site UI

from datetime import timedelta
from django.urls import path
from django.shortcuts import render
from django.db.models import Sum
from django.utils import timezone

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


# @admin.register(TimeEntry)
# class TimeEntryAdmin(admin.ModelAdmin):
#     list_display = ("worker", "project", "work_date", "hours", "status", "entered_by")
#     list_filter = ("status", "project", "work_date")
#     search_fields = ("worker__display_name", "project__name")

from datetime import date

def to_monday(d: date) -> date:
    return d - timedelta(days=d.weekday())

@admin.register(TimeEntry)
class TimeEntryAdmin(admin.ModelAdmin):
    list_display = ("worker", "project", "work_date", "hours", "status", "entered_by")
    list_filter = ("status", "project", "work_date")
    search_fields = ("worker__display_name", "project__name")

    # Optional: discourage manual row editing
    # def has_add_permission(self, request): return False
    # def has_change_permission(self, request, obj=None):
    #     if obj is None: return True
    #     return False

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
        Python aggregation to be DB-agnostic.
        """
        # filters
        week_str = request.GET.get("week")  # YYYY-MM-DD (Monday)
        project_id = request.GET.get("project_id")
        worker_id = request.GET.get("worker_id")

        qs = TimeEntry.objects.select_related("worker", "project").all()

        if project_id:
            qs = qs.filter(project_id=project_id)
        if worker_id:
            qs = qs.filter(worker_id=worker_id)

        # If week provided, constrain to that week (Mon..Sun)
        selected_week = None
        if week_str:
            try:
                selected_week = date.fromisoformat(week_str)
                selected_week = to_monday(selected_week)
                qs = qs.filter(work_date__gte=selected_week, work_date__lte=selected_week + timedelta(days=6))
            except ValueError:
                selected_week = None

        # Default: show last 8 weeks if no week filter
        if not selected_week:
            today = timezone.localdate()
            this_monday = to_monday(today)
            start = this_monday - timedelta(weeks=7)
            qs = qs.filter(work_date__gte=start, work_date__lte=this_monday + timedelta(days=6))

        # Aggregate in python
        buckets = {}
        for e in qs:
            wk = to_monday(e.work_date)
            key = (wk, e.worker_id, e.project_id)
            buckets[key] = buckets.get(key, 0) + float(e.hours)

        # Turn into rows sorted by week desc then worker then project
        rows = []
        for (wk, wid, pid), total in buckets.items():
            rows.append({
                "week_start": wk,
                "worker": None,   # fill later
                "project": None,  # fill later
                "worker_id": wid,
                "project_id": pid,
                "total_hours": round(total, 2),
            })

        # Resolve names (avoid lots of queries)
        worker_map = {w.id: w for w in Worker.objects.filter(id__in=[r["worker_id"] for r in rows])}
        project_map = {p.id: p for p in Project.objects.filter(id__in=[r["project_id"] for r in rows])}
        for r in rows:
            r["worker"] = worker_map.get(r["worker_id"])
            r["project"] = project_map.get(r["project_id"])

        rows.sort(key=lambda r: (r["week_start"], (r["worker"].display_name if r["worker"] else ""), (r["project"].name if r["project"] else "")), reverse=True)

        context = dict(
            self.admin_site.each_context(request),
            rows=rows,
            projects=Project.objects.filter(is_active=True).order_by("name"),
            workers=Worker.objects.filter(is_active=True).order_by("display_name"),
            selected_week=(selected_week.isoformat() if selected_week else ""),
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
        """
        Create Worker if missing. Ensures email is normalized.
        """
        email = (req.email or "").strip().lower()

        # If Worker already exists, do nothing
        worker = Worker.objects.filter(email=email).first()
        if worker:
            # Optionally keep worker active
            if not worker.is_active:
                worker.is_active = True
                worker.save(update_fields=["is_active"])
            return worker

        # Pick a display name
        display_name = (req.requested_name or "").strip()
        if not display_name:
            # fallback: use local part of email
            display_name = email.split("@")[0] if "@" in email else email

        worker = Worker.objects.create(
            display_name=display_name,
            email=email,
            is_active=True,
        )
        return worker

    def save_model(self, request, obj, form, change):
        """
        If status is changed to APPROVED, automatically create Worker (if missing)
        and stamp reviewed_by/reviewed_at.
        """
        # Track previous status if this is an edit
        previous_status = None
        if change and obj.pk:
            previous_status = AccessRequest.objects.filter(pk=obj.pk).values_list("status", flat=True).first()

        # Normalize email
        obj.email = (obj.email or "").strip().lower()

        # If approving now (status becomes APPROVED)
        is_becoming_approved = (obj.status == AccessRequest.Status.APPROVED) and (previous_status != AccessRequest.Status.APPROVED)

        if is_becoming_approved:
            if not obj.reviewed_by:
                obj.reviewed_by = request.user
            if not obj.reviewed_at:
                obj.reviewed_at = timezone.now()

        super().save_model(request, obj, form, change)

        # Create Worker after saving (so obj has pk)
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