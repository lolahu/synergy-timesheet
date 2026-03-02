from django.contrib.auth import get_user_model, login
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.contrib.auth import logout
from django.contrib.auth.decorators import login_required
from datetime import date
from django.db import IntegrityError

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

@login_required
def timesheet_entry(request):
    worker = getattr(request.user, "worker_profile", None)
    if not worker or not worker.is_active:
        return render(request, "core/not_a_worker.html")

    projects = Project.objects.filter(is_active=True).order_by("name")

    context = {
        "projects": projects,
        "today": date.today().isoformat(),
    }

    if request.method == "POST":
        project_id = request.POST.get("project_id")
        work_date = request.POST.get("work_date")
        hours = request.POST.get("hours")
        notes = (request.POST.get("notes") or "").strip()

        # Basic validation (keep it simple)
        error = None
        if not project_id:
            error = "Please choose a project."
        elif not work_date:
            error = "Please choose a date."
        elif not hours:
            error = "Please enter hours."

        if not error:
            project = Project.objects.filter(id=project_id, is_active=True).first()
            if not project:
                error = "Invalid project."

        if not error:
            try:
                entry = TimeEntry.objects.create(
                    worker=worker,
                    project=project,
                    work_date=work_date,
                    hours=hours,
                    notes=notes,
                    entered_by=request.user,
                    status=TimeEntry.Status.SUBMITTED,  # submit immediately (better UX)
                )
                return render(request, "core/timesheet_success.html", {"entry": entry})
            except IntegrityError:
                # UniqueConstraint worker+project+work_date hit
                error = "An entry already exists for this worker/project/date. Please edit it in admin for now."

        context["error"] = error
        context["prev"] = {"project_id": project_id, "work_date": work_date, "hours": hours, "notes": notes}
        return render(request, "core/timesheet_entry.html", context)

    return render(request, "core/timesheet_entry.html", context)