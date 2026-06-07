from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from django import forms
from django.contrib import admin
from django.contrib.admin.widgets import AdminFileWidget
from django.contrib.admin.sites import NotRegistered
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import GroupAdmin as BaseGroupAdmin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.forms import AdminUserCreationForm, UserChangeForm
from django.contrib.auth.models import Group
from django.db.models import Q
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, render
from django.urls import path, reverse
from django.utils import timezone
from django.utils.html import format_html

from . import admin_user  # noqa: F401 -- Customize the Admin Site UI
from .models import ParkingEntry, Project, TimeEntry, Worker
from .permissions import foreman_group_name, user_is_foreman

User = get_user_model()


class AdminReceiptFileValue:
    def __init__(self, value, url):
        self.value = value
        self.url = url

    def __str__(self):
        return str(self.value)


class AdminReceiptFileWidget(AdminFileWidget):
    template_name = "admin/widgets/receipt_clearable_file_input.html"

    def __init__(self, *args, receipt_url=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.receipt_url = receipt_url

    def get_context(self, name, value, attrs):
        context = super().get_context(name, value, attrs)
        if self.receipt_url and context["widget"]["is_initial"]:
            context["widget"]["value"] = AdminReceiptFileValue(
                context["widget"]["value"],
                self.receipt_url,
            )
        return context


class EmailUserCreationForm(AdminUserCreationForm):
    email = forms.EmailField(label="Email")
    username = None

    class Meta(AdminUserCreationForm.Meta):
        model = User
        fields = ("email", "first_name", "last_name", "is_active", "is_staff", "groups")

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(Q(username__iexact=email) | Q(email__iexact=email)).exists():
            raise forms.ValidationError("An account with this email already exists.")
        return email

    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data["email"]
        user.username = user.email
        user.is_superuser = False
        if commit:
            user.save()
            self.save_m2m()
        return user


class EmailUserChangeForm(UserChangeForm):
    email = forms.EmailField(label="Email")
    username = None

    class Meta(UserChangeForm.Meta):
        model = User
        fields = (
            "email",
            "password",
            "first_name",
            "last_name",
            "is_active",
            "is_staff",
            "groups",
            "last_login",
            "date_joined",
        )

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        duplicate = User.objects.filter(Q(username__iexact=email) | Q(email__iexact=email)).exclude(pk=self.instance.pk)
        if duplicate.exists():
            raise forms.ValidationError("An account with this email already exists.")
        return email


def to_monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


class StaffAdminAccessMixin:
    def _is_staff_admin(self, request):
        return request.user.is_active and request.user.is_staff

    def has_module_permission(self, request):
        return self._is_staff_admin(request)

    def has_view_permission(self, request, obj=None):
        return self._is_staff_admin(request)

    def has_add_permission(self, request):
        return self._is_staff_admin(request)

    def has_change_permission(self, request, obj=None):
        return self._is_staff_admin(request)

    def has_delete_permission(self, request, obj=None):
        return self._is_staff_admin(request)


try:
    admin.site.unregister(Group)
except NotRegistered:
    pass


@admin.register(Group)
class GroupAdmin(StaffAdminAccessMixin, BaseGroupAdmin):
    pass


@admin.register(Worker)
class WorkerAdmin(StaffAdminAccessMixin, admin.ModelAdmin):
    list_display = ("display_name", "email", "is_active", "created_at")
    search_fields = ("display_name", "email")
    list_filter = ("is_active",)


@admin.register(Project)
class ProjectAdmin(StaffAdminAccessMixin, admin.ModelAdmin):
    list_display = ("name", "code", "is_active", "created_at")
    search_fields = ("name", "code")
    list_filter = ("is_active",)



@admin.register(TimeEntry)
class TimeEntryAdmin(StaffAdminAccessMixin, admin.ModelAdmin):
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

        week_end = selected_week + timedelta(days=4)

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
            combo_entries[key].append((e.work_date, e.hours))
            worker_map[e.worker_id] = e.worker
            project_map[e.project_id] = e.project

        rows = []
        total_week_hours = Decimal("0")
        total_cumulative_hours = Decimal("0")
        for (wid, pid), entries in combo_entries.items():
            # Weekly hours: sum entries that fall within selected week
            weekly_total = sum(
                (h for d, h in entries if selected_week <= d <= week_end),
                Decimal("0"),
            )

            # Cumulative hours: all entries up to and including week_end
            cumulative = sum(
                (h for d, h in entries if d <= week_end),
                Decimal("0"),
            )
            total_week_hours += weekly_total
            total_cumulative_hours += cumulative

            rows.append({
                "week_start": selected_week,
                "worker": worker_map.get(wid),
                "project": project_map.get(pid),
                "worker_id": wid,
                "project_id": pid,
                "total_hours": weekly_total if weekly_total else "—",
                "cumulative_hours": cumulative,
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
            total_week_hours=total_week_hours,
            total_cumulative_hours=total_cumulative_hours,
        )
        return render(request, "admin/core/timeentry/weekly_dashboard.html", context)



@admin.register(ParkingEntry)
class ParkingEntryAdmin(StaffAdminAccessMixin, admin.ModelAdmin):
    list_display = ("worker", "project", "work_date", "amount", "status", "submitted_by", "receipt_link", "created_at")
    list_filter = ("status", "project", "work_date")
    search_fields = ("worker__display_name", "project__name")
    readonly_fields = ("receipt_preview",)

    def get_urls(self):
        urls = super().get_urls()
        custom = [
            path(
                "<int:object_id>/receipt/",
                self.admin_site.admin_view(self.receipt_view),
                name="core_parkingentry_receipt",
            ),
            path(
                "<int:object_id>/receipt/download/",
                self.admin_site.admin_view(self.receipt_download_view),
                name="core_parkingentry_receipt_download",
            ),
        ]
        return custom + urls

    def receipt_admin_url(self, obj):
        return reverse("admin:core_parkingentry_receipt", args=[obj.pk])

    def receipt_admin_download_url(self, obj):
        return reverse("admin:core_parkingentry_receipt_download", args=[obj.pk])

    def receipt_admin_url_for_id(self, object_id):
        return reverse("admin:core_parkingentry_receipt", args=[object_id])

    def formfield_for_dbfield(self, db_field, request, **kwargs):
        formfield = super().formfield_for_dbfield(db_field, request, **kwargs)
        if db_field.name == "receipt" and formfield:
            object_id = request.resolver_match.kwargs.get("object_id")
            if object_id:
                formfield.widget = AdminReceiptFileWidget(
                    receipt_url=self.receipt_admin_url_for_id(object_id),
                )
        return formfield

    def receipt_view(self, request, object_id):
        return self.receipt_response(request, object_id, as_attachment=False)

    def receipt_download_view(self, request, object_id):
        return self.receipt_response(request, object_id, as_attachment=True)

    def receipt_response(self, request, object_id, as_attachment):
        entry = get_object_or_404(self.get_queryset(request), pk=object_id)
        if not entry.receipt:
            raise Http404("No receipt uploaded.")

        try:
            receipt_file = entry.receipt.open("rb")
        except FileNotFoundError as exc:
            raise Http404("Receipt file not found.") from exc

        return FileResponse(
            receipt_file,
            as_attachment=as_attachment,
            filename=entry.receipt.name.rsplit("/", 1)[-1],
        )

    def receipt_link(self, obj):
        if obj.receipt:
            return format_html(
                '<a href="{}" target="_blank" rel="noopener noreferrer">📎 View</a>'
                ' | <a href="{}">Download</a>',
                self.receipt_admin_url(obj),
                self.receipt_admin_download_url(obj),
            )
        return "—"
    receipt_link.short_description = "Receipt"

    def receipt_preview(self, obj):
        if obj.receipt:
            url = self.receipt_admin_url(obj)
            download_url = self.receipt_admin_download_url(obj)
            name = obj.receipt.name.lower()
            if name.endswith(".pdf"):
                return format_html(
                    '<a href="{}" target="_blank" rel="noopener noreferrer">'
                    '📄 Open PDF in new tab</a> | <a href="{}">Download</a>',
                    url, download_url,
                )
            else:
                return format_html(
                    '<a href="{}" target="_blank" rel="noopener noreferrer">'
                    '<img src="{}" style="max-width: 400px; max-height: 400px; '
                    'border: 1px solid #ccc; border-radius: 4px;" />'
                    '</a><br><a href="{}">Download</a>',
                    url, url, download_url,
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
class UserAdmin(StaffAdminAccessMixin, BaseUserAdmin):
    """
    Extends the default UserAdmin to show pending signups prominently
    and provide a one-click approve action that also activates the Worker profile.
    Username field is hidden — email is used as the login identifier.
    """
    list_display = ("email", "full_name", "role_display", "is_active", "date_joined")
    list_filter = ("is_active", "is_staff", "groups", "date_joined")
    search_fields = ("email", "first_name", "last_name")
    ordering = ("is_active", "-date_joined")  # pending (inactive) shown first
    actions = ["approve_accounts", "deactivate_accounts"]
    form = EmailUserChangeForm
    add_form = EmailUserCreationForm

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
        ("Access", {"fields": ("is_active", "is_staff", "groups")}),
        ("Important dates", {"fields": ("last_login", "date_joined")}),
    )

    def save_model(self, request, obj, form, change):
        # Always keep username in sync with email
        obj.email = obj.email.strip().lower()
        obj.username = obj.email
        obj.is_superuser = False
        super().save_model(request, obj, form, change)

        if obj.email:
            display_name = obj.get_full_name() or obj.email.split("@")[0]
            worker = getattr(obj, "worker_profile", None)
            if worker:
                worker.email = obj.email
                worker.display_name = worker.display_name or display_name
                worker.is_active = obj.is_active
                worker.save(update_fields=["email", "display_name", "is_active", "updated_at"])
            else:
                Worker.objects.get_or_create(
                    email=obj.email,
                    defaults={
                        "display_name": display_name,
                        "is_active": obj.is_active,
                        "user": obj,
                    },
                )

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        user = form.instance
        if user.is_staff:
            foreman_groups = Group.objects.filter(name__iexact=foreman_group_name())
            user.groups.remove(*foreman_groups)

    def full_name(self, obj):
        return obj.get_full_name() or "—"
    full_name.short_description = "Name"

    def role_display(self, obj):
        from django.utils.safestring import mark_safe
        if not obj.is_active:
            return mark_safe('<span style="color: #c0392b; font-weight: bold;">Pending Approval</span>')
        if obj.is_staff:
            return mark_safe('<span style="color: #417690;">Admin</span>')
        if user_is_foreman(obj):
            return mark_safe('<span style="color: #8a6d3b;">Foreman</span>')
        return mark_safe('<span style="color: #27ae60;">Regular Employee</span>')
    role_display.short_description = "Role"

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
