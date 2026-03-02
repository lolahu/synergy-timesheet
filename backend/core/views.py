from django.contrib.auth import get_user_model, login
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.contrib.auth import logout
from django.contrib.auth.decorators import login_required
from django.db import IntegrityError
from django.shortcuts import get_object_or_404
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from .models import AccessRequest, MagicLinkToken, Worker, Project, TimeEntry, ParkingEntry

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

        if email:
            approved = AccessRequest.objects.filter(
                email=email, status=AccessRequest.Status.APPROVED
            ).exists()

            worker = Worker.objects.filter(email=email, is_active=True).first()

            if approved and worker:
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


@login_required
def timesheet_weekly(request):
    # Foreman/admin only
    if not can_enter_for_others(request.user):
        return render(request, "core/not_authorized.html", status=403)

    today = date.today()
    is_monday = today.weekday() == 0
    is_admin = request.user.is_superuser
    this_monday = today - timedelta(days=today.weekday())
    last_monday = this_monday - timedelta(weeks=1)

    # Fridays for display purposes (Mon + 4 days)
    this_friday = this_monday + timedelta(days=4)
    last_friday = last_monday + timedelta(days=4)

    week_str = request.GET.get("week") or request.POST.get("week")

    if is_admin:
        # Admins can pick any week freely
        if week_str:
            try:
                week_start = date.fromisoformat(week_str)
                week_start = week_start - timedelta(days=week_start.weekday())
            except ValueError:
                week_start = this_monday
        else:
            week_start = this_monday
    elif is_monday:
        # Foremen on Monday: can pick this week or last week only
        if week_str:
            try:
                week_start = date.fromisoformat(week_str)
                if week_start not in (this_monday, last_monday):
                    week_start = this_monday
            except ValueError:
                week_start = this_monday
        else:
            week_start = this_monday
    else:
        # Everyone else: locked to current week
        week_start = this_monday

    week_friday = week_start + timedelta(days=4)
    days = [week_start + timedelta(days=i) for i in range(7)]

    projects = list(Project.objects.filter(is_active=True).order_by("name"))
    project_id = request.GET.get("project_id") or request.POST.get("project_id")
    selected_project = Project.objects.filter(id=project_id, is_active=True).first() if project_id else None

    workers = list(Worker.objects.filter(is_active=True).order_by("display_name"))

    # If no project selected yet -> show picker-only mode
    if not selected_project:
        return render(
            request,
            "core/timesheet_weekly.html",
            {
                "needs_project": True,
                "projects": projects,
                "selected_project": None,
                "week_start": week_start,
                "week_friday": week_friday,
                "days": days,
                "workers": workers,
                "grid": {},
                "is_monday": is_monday,
                "this_monday": this_monday,
                "last_monday": last_monday,
                "this_friday": this_friday,
                "last_friday": last_friday,
                "is_admin": is_admin,
            },
        )

    # Prefill existing entries for this project + week — only SUBMITTED
    existing = TimeEntry.objects.filter(
        project=selected_project,
        worker__in=workers,
        work_date__gte=days[0],
        work_date__lte=days[-1],
        status=TimeEntry.Status.SUBMITTED,
    )

    # Key: "{worker_id}_{YYYY-MM-DD}" -> hours
    grid = {f"{e.worker_id}_{e.work_date.isoformat()}": str(e.hours) for e in existing}

    # Workers that already have saved entries this week (for pre-filled rows)
    prefilled_worker_ids = list(dict.fromkeys(e.worker_id for e in existing))
    prefilled_workers = [w for w in workers if w.id in prefilled_worker_ids]

    # Pad up to 10 rows total with blank rows
    blank_row_count = max(0, 10 - len(prefilled_workers))
    extra_blank_rows = range(blank_row_count)

    if request.method == "POST":
        # New row-based format: row_worker[] and row_hours[] are parallel lists
        # row_hours[] has 7 values per worker row (one per day)
        worker_ids = request.POST.getlist("row_worker[]")
        all_hours = request.POST.getlist("row_hours[]")

        for row_index, worker_id_str in enumerate(worker_ids):
            if not worker_id_str:
                continue  # skip rows with no worker selected

            # Extract this row's 7 hour values
            day_hours = all_hours[row_index * 7: row_index * 7 + 7]

            for day_offset, raw in enumerate(day_hours):
                day = days[day_offset]
                day_str = day.isoformat()
                raw = (raw or "").strip()

                # blank = delete only the active SUBMITTED entry, keep history
                if raw == "":
                    TimeEntry.objects.filter(
                        worker_id=worker_id_str,
                        project=selected_project,
                        work_date=day_str,
                        status=TimeEntry.Status.SUBMITTED,
                    ).delete()
                    continue

                try:
                    hours = Decimal(raw)
                except (InvalidOperation, ValueError):
                    continue

                if hours < 0 or hours > 24:
                    continue

                # Mark any existing active entry for this worker/project/day as OVERWRITTEN,
                # then create a fresh SUBMITTED entry to preserve the history.
                existing_qs = TimeEntry.objects.filter(
                    worker_id=worker_id_str,
                    project=selected_project,
                    work_date=day_str,
                ).exclude(status=TimeEntry.Status.OVERWRITTEN)

                if existing_qs.exists():
                    existing_qs.update(status=TimeEntry.Status.OVERWRITTEN)

                TimeEntry.objects.create(
                    worker_id=worker_id_str,
                    project=selected_project,
                    work_date=day_str,
                    hours=hours,
                    notes="",
                    entered_by=request.user,
                    status=TimeEntry.Status.SUBMITTED,
                )

        return redirect(f"/timesheet/success/?project_id={selected_project.id}&week={week_start.isoformat()}&project_name={selected_project.name}")

    return render(
        request,
        "core/timesheet_weekly.html",
        {
            "needs_project": False,
            "projects": projects,
            "selected_project": selected_project,
            "week_start": week_start,
            "week_friday": week_friday,
            "days": days,
            "workers": workers,
            "grid": grid,
            "prefilled_workers": prefilled_workers,
            "extra_blank_rows": extra_blank_rows,
            "is_monday": is_monday,
            "this_monday": this_monday,
            "last_monday": last_monday,
            "this_friday": this_friday,
            "last_friday": last_friday,
            "is_admin": is_admin,
        },
    )


@login_required
def timesheet_success(request):
    project_name = request.GET.get("project_name", "")
    week = request.GET.get("week", "")
    project_id = request.GET.get("project_id", "")
    return render(request, "core/timesheet_success.html", {
        "project_name": project_name,
        "week": week,
        "project_id": project_id,
    })


@login_required
def parking_entry(request):
    projects = Project.objects.filter(is_active=True).order_by("name")
    workers = Worker.objects.filter(is_active=True).order_by("display_name")
    today = date.today().isoformat()

    # Pre-select the logged-in user's own worker profile if it exists
    own_worker = getattr(request.user, "worker_profile", None)

    context = {
        "projects": projects,
        "workers": workers,
        "today": today,
        "own_worker": own_worker,
    }

    if request.method == "POST":
        worker_id = request.POST.get("worker_id", "").strip()
        project_id = request.POST.get("project_id", "").strip()
        work_date = request.POST.get("work_date", "").strip()
        amount_raw = request.POST.get("amount", "").strip()
        notes = request.POST.get("notes", "").strip()
        receipt_file = request.FILES.get("receipt")

        error = None
        worker = None
        project = None

        if not worker_id:
            error = "Please select a worker."
        else:
            worker = Worker.objects.filter(id=worker_id, is_active=True).first()
            if not worker:
                error = "Invalid worker selected."

        if not project_id:
            error = error or "Please select a project."
        else:
            project = Project.objects.filter(id=project_id, is_active=True).first()
            if not project:
                error = error or "Invalid project."

        if not work_date:
            error = error or "Please select a date."

        if not amount_raw:
            error = error or "Please enter the parking amount."
        else:
            try:
                amount = Decimal(amount_raw)
                if amount <= 0:
                    error = error or "Amount must be greater than 0."
            except (InvalidOperation, ValueError):
                error = error or "Invalid amount."

        # Validate file type if provided
        if receipt_file:
            allowed_types = ["image/jpeg", "image/png", "image/gif", "image/webp", "application/pdf"]
            if receipt_file.content_type not in allowed_types:
                error = error or "Receipt must be an image (JPG, PNG, GIF, WEBP) or PDF."

        if error:
            context["error"] = error
            context["prev"] = {
                "worker_id": worker_id,
                "project_id": project_id,
                "work_date": work_date,
                "amount": amount_raw,
                "notes": notes,
            }
            return render(request, "core/parking_entry.html", context)

        entry = ParkingEntry(
            worker=worker,
            project=project,
            work_date=work_date,
            amount=amount,
            notes=notes,
            submitted_by=request.user,
            status=ParkingEntry.Status.SUBMITTED,
        )
        if receipt_file:
            entry.receipt = receipt_file
        entry.save()

        return redirect(f"/parking/success/?project_name={project.name}&work_date={work_date}&amount={amount_raw}")

    return render(request, "core/parking_entry.html", context)


@login_required
def parking_success(request):
    return render(request, "core/parking_success.html", {
        "project_name": request.GET.get("project_name", ""),
        "work_date": request.GET.get("work_date", ""),
        "amount": request.GET.get("amount", ""),
    })