from django.contrib.auth import get_user_model, login
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.contrib.auth import logout
from django.contrib.auth.decorators import login_required
from datetime import date
from django.db import IntegrityError
from django.shortcuts import get_object_or_404
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from .models import AccessRequest, MagicLinkToken, Worker, Project, TimeEntry

User = get_user_model()


def home(request):
    return render(request, "core/home.html")

def request_access(request):
    if request.method == "POST":
        email = (request.POST.get("email") or "").strip().lower()
        name = (request.POST.get("name") or "").strip()
        phone = (request.POST.get("phone") or "").strip()

        if email:
            # Upsert: if they re-submit, keep status as-is but update name/phone
            obj, created = AccessRequest.objects.get_or_create(email=email)
            obj.requested_name = name
            obj.requested_phone = phone
            if created:
                obj.status = AccessRequest.Status.PENDING
            obj.save()

        # Always return same message (prevents email enumeration)
        return render(request, "core/request_access_done.html")

    return render(request, "core/request_access.html")


def login_request(request):
    """
    Worker enters email. If approved (and active), print a magic link to terminal.
    """
    if request.method == "POST":
        email = (request.POST.get("email") or "").strip().lower()

        # Always show same UI result
        # Only approved emails will actually get a printed link.
        if email:
            approved = AccessRequest.objects.filter(
                email=email, status=AccessRequest.Status.APPROVED
            ).exists()

            # Also require a Worker record to exist and be active
            worker = Worker.objects.filter(email=email, is_active=True).first()

            if approved and worker:
                # Ensure a User exists and link to Worker
                user, _ = User.objects.get_or_create(
                    username=email, defaults={"email": email, "is_active": True}
                )
                if not user.email:
                    user.email = email
                if not user.is_active:
                    user.is_active = True
                user.save()

                if worker.user_id != user.id:
                    worker.user = user
                    worker.save(update_fields=["user"])

                token_obj, raw = MagicLinkToken.create_for_user(user, ttl_minutes=15)
                link = request.build_absolute_uri(f"/magic/{raw}/")
                print("\n=== MAGIC LOGIN LINK ===")
                print(link)
                print("========================\n")

        return render(request, "core/login_requested.html")

    return render(request, "core/login_request.html")

def magic_login(request, token: str):
    token_hash = MagicLinkToken.hash_token(token)
    obj = MagicLinkToken.objects.filter(token_hash=token_hash).select_related("user").first()
    if not obj or not obj.is_valid():
        return HttpResponse("This login link is invalid or expired.", status=400)

    obj.mark_used()
    login(request, obj.user)
    return redirect("home")

def logout_view(request):
    logout(request)
    return redirect("home")

def can_enter_for_others(user) -> bool:
    return user.is_staff or user.groups.filter(name="FOREMAN").exists()

def get_target_worker(request):
    """
    If foreman/admin: allow selecting worker via ?worker_id= or POST worker_id.
    Otherwise: use own worker_profile.
    """
    if can_enter_for_others(request.user):
        worker_id = request.POST.get("worker_id") or request.GET.get("worker_id")
        if worker_id:
            return Worker.objects.filter(id=worker_id, is_active=True).first()
    return getattr(request.user, "worker_profile", None)

@login_required
def timesheet_entry(request):
    worker = get_target_worker(request)
    if not worker or not worker.is_active:
        return render(request, "core/not_a_worker.html")

    projects = Project.objects.filter(is_active=True).order_by("name")
    workers = Worker.objects.filter(is_active=True).order_by("display_name") if can_enter_for_others(request.user) else None

    context = {
        "projects": projects,
        "workers": workers,
        "selected_worker": worker,
        "today": date.today().isoformat(),
        "can_pick_worker": can_enter_for_others(request.user),
    }

    if request.method == "POST":
        project_id = request.POST.get("project_id")
        work_date = request.POST.get("work_date")
        hours_raw = (request.POST.get("hours") or "").strip()
        notes = (request.POST.get("notes") or "").strip()

        error = None
        project = None

        if not project_id:
            error = "Please choose a project."
        else:
            project = Project.objects.filter(id=project_id, is_active=True).first()
            if not project:
                error = "Invalid project."

        if not work_date:
            error = error or "Please choose a date."

        if not hours_raw:
            error = error or "Please enter hours."
        else:
            try:
                hours = Decimal(hours_raw)
                if hours < 0 or hours > 24:
                    error = error or "Hours must be between 0 and 24."
            except (InvalidOperation, ValueError):
                error = error or "Invalid hours."

        if error:
            context["error"] = error
            context["prev"] = {"project_id": project_id, "work_date": work_date, "hours": hours_raw, "notes": notes}
            return render(request, "core/timesheet_entry.html", context)

        # UPSERT: update if exists, else create
        entry, created = TimeEntry.objects.get_or_create(
            worker=worker,
            project=project,
            work_date=work_date,
            defaults={
                "hours": hours,
                "notes": notes,
                "entered_by": request.user,
                "status": TimeEntry.Status.SUBMITTED,
            },
        )
        if not created:
            entry.hours = hours
            entry.notes = notes
            entry.entered_by = request.user
            entry.status = TimeEntry.Status.SUBMITTED
            entry.save()

        return render(
            request,
            "core/timesheet_success.html",
            {"entry": entry, "created": created},
        )

    return render(request, "core/timesheet_entry.html", context)

@login_required
def timesheet_weekly(request):
    worker = get_target_worker(request)
    if not worker or not worker.is_active:
        return render(request, "core/not_a_worker.html")

    # Choose week start (Monday)
    week_str = request.GET.get("week")  # YYYY-MM-DD
    if week_str:
        week_start = date.fromisoformat(week_str)
    else:
        today = date.today()
        week_start = today - timedelta(days=today.weekday())  # Monday

    # Normalize to Monday if user passed some other day
    week_start = week_start - timedelta(days=week_start.weekday())
    days = [week_start + timedelta(days=i) for i in range(7)]
    day_labels = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

    projects = list(Project.objects.filter(is_active=True).order_by("name"))
    workers = Worker.objects.filter(is_active=True).order_by("display_name") if can_enter_for_others(request.user) else None

    # Existing entries in that week for this worker
    existing = TimeEntry.objects.filter(
        worker=worker,
        work_date__gte=days[0],
        work_date__lte=days[-1],
        project__in=projects,
    ).select_related("project")

    # Map (project_id, date_iso) -> hours
    grid = {}
    for e in existing:
        grid[(e.project_id, e.work_date.isoformat())] = str(e.hours)

    if request.method == "POST":
        # Upsert non-empty cells
        for p in projects:
            for d in days:
                field = f"h_{p.id}_{d.isoformat()}"
                raw = (request.POST.get(field) or "").strip()
                if raw == "":
                    continue  # leave unchanged for v1

                try:
                    hours = Decimal(raw)
                except Exception:
                    continue  # skip invalid cell for v1 (we can add errors later)

                if hours < 0 or hours > 24:
                    continue

                entry, created = TimeEntry.objects.get_or_create(
                    worker=worker,
                    project=p,
                    work_date=d,
                    defaults={
                        "hours": hours,
                        "notes": "",
                        "entered_by": request.user,
                        "status": TimeEntry.Status.SUBMITTED,
                    },
                )
                if not created:
                    entry.hours = hours
                    entry.entered_by = request.user
                    entry.status = TimeEntry.Status.SUBMITTED
                    entry.save()

        return redirect(f"/timesheet/weekly/?week={week_start.isoformat()}&worker_id={worker.id}")

    return render(
        request,
        "core/timesheet_weekly.html",
        {
            "projects": projects,
            "workers": workers,
            "selected_worker": worker,
            "can_pick_worker": can_enter_for_others(request.user),
            "week_start": week_start,
            "days": days,
            "day_labels": day_labels,
            "grid": grid,
        },
    )