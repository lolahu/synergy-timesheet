# core/models.py
from django.utils import timezone
import secrets
import hashlib
from datetime import timedelta
from django.conf import settings
from django.db import models

class Worker(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="worker_profile",
    )

    display_name = models.CharField(max_length=120)
    email = models.EmailField(unique=True)
    phone = models.CharField(max_length=30, blank=True, null=True)

    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.display_name


class Project(models.Model):
    name = models.CharField(max_length=160, unique=True)
    code = models.CharField(max_length=50, blank=True)
    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class RateOverride(models.Model):
    worker = models.ForeignKey(Worker, on_delete=models.CASCADE, related_name="rate_overrides")
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="rate_overrides")
    hourly_rate = models.DecimalField(max_digits=10, decimal_places=2)

    effective_from = models.DateField(blank=True, null=True)
    effective_to = models.DateField(blank=True, null=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["worker", "project", "effective_from"], name="uniq_worker_project_effective")
        ]

    def __str__(self):
        return f"{self.worker} / {self.project} @ {self.hourly_rate}"


class TimeEntry(models.Model):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        SUBMITTED = "SUBMITTED", "Submitted"
        APPROVED = "APPROVED", "Approved"
        REJECTED = "REJECTED", "Rejected"
        OVERWRITTEN = "OVERWRITTEN", "Overwritten"  # ← new: previous entry replaced by a newer one

    worker = models.ForeignKey(Worker, on_delete=models.PROTECT, related_name="time_entries")
    project = models.ForeignKey(Project, on_delete=models.PROTECT, related_name="time_entries")

    work_date = models.DateField()
    hours = models.DecimalField(max_digits=5, decimal_places=2)
    notes = models.CharField(max_length=500, blank=True)

    entered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="time_entries_entered",
        help_text="Who typed this entry (worker/foreman/admin).",
    )

    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)

    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="time_entries_reviewed",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_notes = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["work_date"]),
            models.Index(fields=["status", "work_date"]),
            models.Index(fields=["project", "work_date"]),
            models.Index(fields=["worker", "work_date"]),
        ]
        # Removed the unique constraint on (worker, project, work_date) so that
        # overwritten entries can coexist with new ones for the same day.

    def __str__(self):
        return f"{self.worker} {self.project} {self.work_date} {self.hours}"


class AccessRequest(models.Model):
    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        APPROVED = "APPROVED", "Approved"
        REJECTED = "REJECTED", "Rejected"

    email = models.EmailField(unique=True)
    requested_name = models.CharField(max_length=120, blank=True)
    requested_phone = models.CharField(max_length=30, blank=True)

    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    requested_at = models.DateTimeField(auto_now_add=True)

    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="access_requests_reviewed",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_notes = models.TextField(blank=True)

    def __str__(self):
        return f"{self.email} ({self.status})"


class MagicLinkToken(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="magic_tokens")
    token_hash = models.CharField(max_length=64, unique=True)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    @staticmethod
    def make_token() -> str:
        return secrets.token_urlsafe(32)

    @staticmethod
    def hash_token(raw_token: str) -> str:
        return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()

    @classmethod
    def create_for_user(cls, user, ttl_minutes: int = 15):
        raw = cls.make_token()
        token_hash = cls.hash_token(raw)
        obj = cls.objects.create(
            user=user,
            token_hash=token_hash,
            expires_at=timezone.now() + timedelta(minutes=ttl_minutes),
        )
        return obj, raw

    def is_valid(self) -> bool:
        return self.used_at is None and timezone.now() < self.expires_at

    def mark_used(self):
        self.used_at = timezone.now()
        self.save(update_fields=["used_at"])

    def __str__(self):
        return f"{self.user.email} exp={self.expires_at} used={bool(self.used_at)}"