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
    this_monday = today - timedelta(days=today.weekday())
    last_monday = this_monday - timedelta(weeks=1)

    # On Mondays, allow choosing this week or last week
    # On all other days, lock to the current week
    if is_monday:
        week_str = request.GET.get("week") or request.POST.get("week")
        if week_str:
            try:
                week_start = date.fromisoformat(week_str)
                # Safety: only allow this_monday or last_monday
                if week_start not in (this_monday, last_monday):
                    week_start = this_monday
            except ValueError:
                week_start = this_monday
        else:
            week_start = this_monday
    else:
        week_start = this_monday

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
                "days": days,
                "workers": workers,
                "grid": {},
                "is_monday": is_monday,
                "this_monday": this_monday,
                "last_monday": last_monday,
            },
        )

    # Prefill existing entries for this project + week for ALL workers
    existing = TimeEntry.objects.filter(
        project=selected_project,
        worker__in=workers,
        work_date__gte=days[0],
        work_date__lte=days[-1],
    )

    # Key: "{worker_id}_{YYYY-MM-DD}" -> hours
    grid = {f"{e.worker_id}_{e.work_date.isoformat()}": str(e.hours) for e in existing}

    if request.method == "POST":
        for key, raw in request.POST.items():
            if not key.startswith("h_"):
                continue

            parts = key.split("_", 2)  # ["h", "<worker_id>", "<YYYY-MM-DD>"]
            if len(parts) != 3:
                continue

            _, worker_id_str, day_str = parts
            raw = (raw or "").strip()

            # blank = delete
            if raw == "":
                TimeEntry.objects.filter(
                    worker_id=worker_id_str,
                    project=selected_project,
                    work_date=day_str,
                ).delete()
                continue

            try:
                hours = Decimal(raw)
            except (InvalidOperation, ValueError):
                continue

            if hours < 0 or hours > 24:
                continue

            entry, created = TimeEntry.objects.get_or_create(
                worker_id=worker_id_str,
                project=selected_project,
                work_date=day_str,
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
                entry.save(update_fields=["hours", "entered_by", "status", "updated_at"])

        return redirect(f"/timesheet/success/?project_id={selected_project.id}&week={week_start.isoformat()}&project_name={selected_project.name}")

    return render(
        request,
        "core/timesheet_weekly.html",
        {
            "needs_project": False,
            "projects": projects,
            "selected_project": selected_project,
            "week_start": week_start,
            "days": days,
            "workers": workers,
            "grid": grid,
            "is_monday": is_monday,
            "this_monday": this_monday,
            "last_monday": last_monday,
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


# def get_target_worker(request, *, allow_none_for_foreman: bool = False):
#     """
#     - Regular worker: return their own worker_profile
#     - Foreman/admin: if worker_id provided, return that worker
#       otherwise:
#         - if allow_none_for_foreman=True, return None (so UI can show picker)
#         - else fall back to None
#     """
#     if can_enter_for_others(request.user):
#         worker_id = request.POST.get("worker_id") or request.GET.get("worker_id")
#         if worker_id:
#             return Worker.objects.filter(id=worker_id, is_active=True).first()
#         return None if allow_none_for_foreman else None

#     return getattr(request.user, "worker_profile", None)


# @login_required
# def timesheet_entry(request):
#     worker = get_target_worker(request)
#     if not worker or not worker.is_active:
#         return render(request, "core/not_a_worker.html")

#     projects = Project.objects.filter(is_active=True).order_by("name")
#     workers = Worker.objects.filter(is_active=True).order_by("display_name") if can_enter_for_others(request.user) else None

#     context = {
#         "projects": projects,
#         "workers": workers,
#         "selected_worker": worker,
#         "today": date.today().isoformat(),
#         "can_pick_worker": can_enter_for_others(request.user),
#     }

#     if request.method == "POST":
#         project_id = request.POST.get("project_id")
#         work_date = request.POST.get("work_date")
#         hours_raw = (request.POST.get("hours") or "").strip()
#         notes = (request.POST.get("notes") or "").strip()

#         error = None
#         project = None

#         if not project_id:
#             error = "Please choose a project."
#         else:
#             project = Project.objects.filter(id=project_id, is_active=True).first()
#             if not project:
#                 error = "Invalid project."

#         if not work_date:
#             error = error or "Please choose a date."

#         if not hours_raw:
#             error = error or "Please enter hours."
#         else:
#             try:
#                 hours = Decimal(hours_raw)
#                 if hours < 0 or hours > 24:
#                     error = error or "Hours must be between 0 and 24."
#             except (InvalidOperation, ValueError):
#                 error = error or "Invalid hours."

#         if error:
#             context["error"] = error
#             context["prev"] = {"project_id": project_id, "work_date": work_date, "hours": hours_raw, "notes": notes}
#             return render(request, "core/timesheet_entry.html", context)

#         # UPSERT: update if exists, else create
#         entry, created = TimeEntry.objects.get_or_create(
#             worker=worker,
#             project=project,
#             work_date=work_date,
#             defaults={
#                 "hours": hours,
#                 "notes": notes,
#                 "entered_by": request.user,
#                 "status": TimeEntry.Status.SUBMITTED,
#             },
#         )
#         if not created:
#             entry.hours = hours
#             entry.notes = notes
#             entry.entered_by = request.user
#             entry.status = TimeEntry.Status.SUBMITTED
#             entry.save()

#         return render(
#             request,
#             "core/timesheet_success.html",
#             {"entry": entry, "created": created},
#         )

#     return render(request, "core/timesheet_entry.html", context)


