from django.contrib.auth import get_user_model, login, logout, authenticate
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import PasswordResetForm
from django.shortcuts import redirect, render
from django.db import IntegrityError
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from .models import Worker, Project, TimeEntry, ParkingEntry

User = get_user_model()


# ── Auth ──────────────────────────────────────────────────────────────────────

def home(request):
    return render(request, "core/home.html")


def login_view(request):
    if request.user.is_authenticated:
        return redirect("home")

    error = None
    if request.method == "POST":
        email = (request.POST.get("email") or "").strip().lower()
        password = request.POST.get("password") or ""

        # Django's authenticate expects username — we use email as username
        user = authenticate(request, username=email, password=password)

        if user is None:
            error = "Invalid email or password."
        elif not user.is_active:
            error = "Your account is pending approval. Please wait for an admin to activate it."
        else:
            login(request, user)
            return redirect("home")

    return render(request, "core/login.html", {"error": error})


def logout_view(request):
    logout(request)
    return redirect("login")


def signup_view(request):
    if request.user.is_authenticated:
        return redirect("home")

    error = None
    if request.method == "POST":
        email = (request.POST.get("email") or "").strip().lower()
        name = (request.POST.get("name") or "").strip()
        phone = (request.POST.get("phone") or "").strip()
        password1 = request.POST.get("password1") or ""
        password2 = request.POST.get("password2") or ""

        if not email:
            error = "Email is required."
        elif not name:
            error = "Name is required."
        elif not password1:
            error = "Password is required."
        elif len(password1) < 8:
            error = "Password must be at least 8 characters."
        elif password1 != password2:
            error = "Passwords do not match."
        elif User.objects.filter(username=email).exists():
            error = "An account with this email already exists."
        else:
            # Create user as inactive — admin must approve before they can log in
            user = User.objects.create_user(
                username=email,
                email=email,
                password=password1,
                is_active=False,
            )
            user.first_name = name
            user.save()

            # Create a linked Worker profile
            Worker.objects.get_or_create(
                email=email,
                defaults={
                    "display_name": name,
                    "phone": phone,
                    "is_active": False,  # also inactive until admin approves
                    "user": user,
                },
            )

            return render(request, "core/signup_done.html", {"email": email})

    return render(request, "core/signup.html", {
        "error": error,
        "prev": request.POST,
    })


# ── Helpers ───────────────────────────────────────────────────────────────────

def can_enter_for_others(user) -> bool:
    return user.is_staff or user.groups.filter(name="FOREMAN").exists()


# ── Timesheet ─────────────────────────────────────────────────────────────────

@login_required
def timesheet_weekly(request):
    if not can_enter_for_others(request.user):
        return render(request, "core/not_authorized.html", status=403)

    today = date.today()
    is_monday = today.weekday() == 0
    is_admin = request.user.is_superuser
    this_monday = today - timedelta(days=today.weekday())
    last_monday = this_monday - timedelta(weeks=1)

    this_friday = this_monday + timedelta(days=4)
    last_friday = last_monday + timedelta(days=4)

    week_str = request.GET.get("week") or request.POST.get("week")

    if is_admin:
        if week_str:
            try:
                week_start = date.fromisoformat(week_str)
                week_start = week_start - timedelta(days=week_start.weekday())
            except ValueError:
                week_start = this_monday
        else:
            week_start = this_monday
    elif is_monday:
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
        week_start = this_monday

    week_friday = week_start + timedelta(days=4)
    days = [week_start + timedelta(days=i) for i in range(7)]

    projects = list(Project.objects.filter(is_active=True).order_by("name"))
    project_id = request.GET.get("project_id") or request.POST.get("project_id")
    selected_project = Project.objects.filter(id=project_id, is_active=True).first() if project_id else None

    workers = list(Worker.objects.filter(is_active=True).order_by("display_name"))

    if not selected_project:
        return render(request, "core/timesheet_weekly.html", {
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
        })

    existing = TimeEntry.objects.filter(
        project=selected_project,
        worker__in=workers,
        work_date__gte=days[0],
        work_date__lte=days[-1],
        status=TimeEntry.Status.SUBMITTED,
    )

    grid = {f"{e.worker_id}_{e.work_date.isoformat()}": str(e.hours) for e in existing}
    prefilled_worker_ids = list(dict.fromkeys(e.worker_id for e in existing))
    prefilled_workers = [w for w in workers if w.id in prefilled_worker_ids]
    extra_blank_rows = range(max(0, 10 - len(prefilled_workers)))

    if request.method == "POST":
        worker_ids = request.POST.getlist("row_worker[]")
        all_hours = request.POST.getlist("row_hours[]")

        for row_index, worker_id_str in enumerate(worker_ids):
            if not worker_id_str:
                continue

            day_hours = all_hours[row_index * 7: row_index * 7 + 7]

            for day_offset, raw in enumerate(day_hours):
                day = days[day_offset]
                day_str = day.isoformat()
                raw = (raw or "").strip()

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

    return render(request, "core/timesheet_weekly.html", {
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
    })


@login_required
def timesheet_success(request):
    return render(request, "core/timesheet_success.html", {
        "project_name": request.GET.get("project_name", ""),
        "week": request.GET.get("week", ""),
        "project_id": request.GET.get("project_id", ""),
    })


# ── Parking ───────────────────────────────────────────────────────────────────

@login_required
def parking_entry(request):
    projects = Project.objects.filter(is_active=True).order_by("name")
    workers = Worker.objects.filter(is_active=True).order_by("display_name")
    today = date.today().isoformat()
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

        if receipt_file:
            allowed_types = [
                "image/jpeg", "image/png", "image/gif",
                "image/webp", "image/heic", "image/heif", "application/pdf",
            ]
            max_size_bytes = 10 * 1024 * 1024
            if receipt_file.content_type not in allowed_types:
                error = error or "Receipt must be an image (JPG, PNG, HEIC, WEBP) or PDF."
            elif receipt_file.size > max_size_bytes:
                error = error or f"Receipt is too large ({receipt_file.size // (1024*1024)}MB). Maximum is 10MB."

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