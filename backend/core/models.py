# core/models.py
from django.utils import timezone
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



class TimeEntry(models.Model):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        SUBMITTED = "SUBMITTED", "Submitted"
        APPROVED = "APPROVED", "Approved"
        REJECTED = "REJECTED", "Rejected"
        OVERWRITTEN = "OVERWRITTEN", "Overwritten"

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

    def __str__(self):
        return f"{self.worker} {self.project} {self.work_date} {self.hours}"


class ParkingEntry(models.Model):
    class Status(models.TextChoices):
        SUBMITTED = "SUBMITTED", "Submitted"
        APPROVED = "APPROVED", "Approved"
        REJECTED = "REJECTED", "Rejected"

    worker = models.ForeignKey(Worker, on_delete=models.PROTECT, related_name="parking_entries")
    project = models.ForeignKey(Project, on_delete=models.PROTECT, related_name="parking_entries")

    work_date = models.DateField()
    amount = models.DecimalField(max_digits=8, decimal_places=2, help_text="Parking cost in dollars")
    receipt = models.FileField(upload_to="parking_receipts/%Y/%m/", blank=True, null=True, help_text="Photo or PDF of parking receipt (JPG, PNG, HEIC, WEBP, PDF — max 10MB)")
    notes = models.CharField(max_length=500, blank=True)

    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="parking_entries_submitted",
    )

    status = models.CharField(max_length=20, choices=Status.choices, default=Status.SUBMITTED)

    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="parking_entries_reviewed",
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

    def __str__(self):
        return f"{self.worker} {self.project} {self.work_date} ${self.amount}"