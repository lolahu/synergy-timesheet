from datetime import date
from decimal import Decimal
import shutil
import tempfile

from django.contrib import admin as django_admin
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import ParkingEntry, Project, TimeEntry, Worker
from .permissions import can_enter_for_others, user_is_foreman
from .admin import EmailUserCreationForm, EmailUserChangeForm, UserAdmin as SynergyUserAdmin


User = get_user_model()


class EmailLoginIdentityTests(TestCase):
    def test_signup_sets_username_to_email(self):
        response = self.client.post(
            reverse("signup"),
            {
                "email": "NewUser@Example.com",
                "name": "New User",
                "phone": "555-0100",
                "password1": "strong-pass-123",
                "password2": "strong-pass-123",
            },
        )

        self.assertEqual(response.status_code, 200)
        user = User.objects.get(email="newuser@example.com")
        self.assertEqual(user.username, "newuser@example.com")

    def test_signup_rejects_duplicate_email_case_insensitively(self):
        User.objects.create_user(
            username="person@example.com",
            email="person@example.com",
            password="pass",
        )

        response = self.client.post(
            reverse("signup"),
            {
                "email": "PERSON@example.com",
                "name": "Person",
                "password1": "strong-pass-123",
                "password2": "strong-pass-123",
            },
        )

        self.assertContains(response, "An account with this email already exists.")

    def test_admin_creation_form_hides_username_and_mirrors_email(self):
        form = EmailUserCreationForm(data={
            "email": "Admin@Example.com",
            "password1": "strong-pass-123",
            "password2": "strong-pass-123",
            "is_active": "on",
            "is_staff": "on",
        })

        self.assertTrue(form.is_valid(), form.errors)
        self.assertNotIn("username", form.fields)

        user = form.save()
        self.assertEqual(user.email, "admin@example.com")
        self.assertEqual(user.username, "admin@example.com")
        self.assertTrue(user.is_staff)
        self.assertFalse(user.is_superuser)

    def test_admin_change_form_rejects_duplicate_email_case_insensitively(self):
        existing = User.objects.create_user(
            username="existing@example.com",
            email="existing@example.com",
            password="pass",
        )
        user = User.objects.create_user(
            username="user@example.com",
            email="user@example.com",
            password="pass",
        )

        form = EmailUserChangeForm(data={
            "email": "EXISTING@example.com",
            "password": user.password,
            "first_name": "",
            "last_name": "",
            "is_active": "on",
        }, instance=user)

        self.assertFalse(form.is_valid())
        self.assertIn("email", form.errors)
        self.assertEqual(existing.email, "existing@example.com")

    def test_admin_save_keeps_username_and_worker_email_in_sync(self):
        user = User.objects.create_user(
            username="old@example.com",
            email="old@example.com",
            password="pass",
        )
        worker = Worker.objects.create(
            user=user,
            display_name="Worker Name",
            email="old@example.com",
        )

        user.email = "NEW@Example.com"
        SynergyUserAdmin(User, django_admin.site).save_model(None, user, None, True)

        user.refresh_from_db()
        worker.refresh_from_db()
        self.assertEqual(user.email, "new@example.com")
        self.assertEqual(user.username, "new@example.com")
        self.assertEqual(worker.email, "new@example.com")


class ForemanPermissionTests(TestCase):
    @override_settings(FOREMAN_GROUP_NAME="Foreman")
    def test_foreman_access_uses_configured_group_case_insensitively(self):
        user = User.objects.create_user(username="foreman@example.com", password="pass")
        group = Group.objects.create(name="FOREMAN")
        user.groups.add(group)

        self.assertTrue(user_is_foreman(user))
        self.assertTrue(can_enter_for_others(user))

    def test_staff_can_enter_for_others_without_foreman_group(self):
        user = User.objects.create_user(
            username="admin@example.com",
            password="pass",
            is_staff=True,
        )

        self.assertTrue(can_enter_for_others(user))


class GroupAdminAccessTests(TestCase):
    def test_staff_admin_can_create_foreman_group_without_superuser(self):
        admin_user = User.objects.create_user(
            username="admin@example.com",
            email="admin@example.com",
            password="pass",
            is_staff=True,
        )
        self.client.force_login(admin_user)

        response = self.client.post(
            reverse("admin:auth_group_add"),
            {
                "name": "Foreman",
                "permissions": [],
                "_save": "Save",
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(Group.objects.filter(name="Foreman").exists())
        admin_user.refresh_from_db()
        self.assertFalse(admin_user.is_superuser)


class WeeklyDashboardTests(TestCase):
    def setUp(self):
        self.admin_user = User.objects.create_user(
            username="admin@example.com",
            email="admin@example.com",
            password="pass",
            is_staff=True,
        )
        self.worker = Worker.objects.create(
            display_name="A Worker",
            email="worker@example.com",
        )
        self.project = Project.objects.create(name="A Project")

    def test_weekly_dashboard_provides_footer_totals_for_selected_friday_week(self):
        self.client.force_login(self.admin_user)

        TimeEntry.objects.create(
            worker=self.worker,
            project=self.project,
            work_date=date(2026, 5, 15),
            hours=Decimal("5.00"),
            status=TimeEntry.Status.APPROVED,
        )
        TimeEntry.objects.create(
            worker=self.worker,
            project=self.project,
            work_date=date(2026, 5, 18),
            hours=Decimal("1.10"),
            status=TimeEntry.Status.SUBMITTED,
        )
        TimeEntry.objects.create(
            worker=self.worker,
            project=self.project,
            work_date=date(2026, 5, 22),
            hours=Decimal("2.20"),
            status=TimeEntry.Status.APPROVED,
        )
        TimeEntry.objects.create(
            worker=self.worker,
            project=self.project,
            work_date=date(2026, 5, 23),
            hours=Decimal("4.00"),
            status=TimeEntry.Status.SUBMITTED,
        )
        TimeEntry.objects.create(
            worker=self.worker,
            project=self.project,
            work_date=date(2026, 5, 22),
            hours=Decimal("8.00"),
            status=TimeEntry.Status.REJECTED,
        )

        response = self.client.get(
            reverse("admin:core_timeentry_weekly_dashboard"),
            {"week": "2026-05-22"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["total_week_hours"], Decimal("3.30"))
        self.assertEqual(response.context["total_cumulative_hours"], Decimal("8.30"))


class ParkingEntryWorkerRestrictionTests(TestCase):
    def setUp(self):
        self.project = Project.objects.create(name="A Project")
        self.other_worker = Worker.objects.create(
            display_name="Other Worker",
            email="other@example.com",
        )

    def submit_parking(self, user, posted_worker):
        self.client.force_login(user)
        return self.client.post(
            reverse("parking_entry"),
            {
                "worker_id": str(posted_worker.pk),
                "project_id": str(self.project.pk),
                "work_date": "2026-06-06",
                "amount": "12.50",
                "notes": "downtown lot",
            },
        )

    def test_parking_form_only_shows_logged_in_worker(self):
        user = User.objects.create_user(
            username="worker@example.com",
            email="worker@example.com",
            password="pass",
        )
        Worker.objects.create(
            user=user,
            display_name="Own Worker",
            email="worker@example.com",
        )
        self.client.force_login(user)

        response = self.client.get(reverse("parking_entry"))

        self.assertContains(response, "Own Worker")
        self.assertNotContains(response, "Other Worker")
        self.assertNotContains(response, 'name="worker_id"')

    def test_parking_submission_uses_logged_in_worker_even_if_post_uses_another_worker(self):
        user = User.objects.create_user(
            username="worker@example.com",
            email="worker@example.com",
            password="pass",
        )
        own_worker = Worker.objects.create(
            user=user,
            display_name="Own Worker",
            email="worker@example.com",
        )

        response = self.submit_parking(user, self.other_worker)

        self.assertEqual(response.status_code, 302)
        entry = ParkingEntry.objects.get()
        self.assertEqual(entry.worker, own_worker)

    def test_staff_parking_submission_still_uses_logged_in_worker(self):
        user = User.objects.create_user(
            username="admin@example.com",
            email="admin@example.com",
            password="pass",
            is_staff=True,
        )
        own_worker = Worker.objects.create(
            user=user,
            display_name="Admin Worker",
            email="admin-worker@example.com",
        )

        response = self.submit_parking(user, self.other_worker)

        self.assertEqual(response.status_code, 302)
        entry = ParkingEntry.objects.get()
        self.assertEqual(entry.worker, own_worker)

    @override_settings(FOREMAN_GROUP_NAME="Foreman")
    def test_foreman_parking_submission_still_uses_logged_in_worker(self):
        user = User.objects.create_user(
            username="foreman@example.com",
            email="foreman@example.com",
            password="pass",
        )
        group = Group.objects.create(name="Foreman")
        user.groups.add(group)
        own_worker = Worker.objects.create(
            user=user,
            display_name="Foreman Worker",
            email="foreman-worker@example.com",
        )

        response = self.submit_parking(user, self.other_worker)

        self.assertEqual(response.status_code, 302)
        entry = ParkingEntry.objects.get()
        self.assertEqual(entry.worker, own_worker)

    def test_parking_submission_requires_active_worker_profile(self):
        user = User.objects.create_user(
            username="unlinked@example.com",
            email="unlinked@example.com",
            password="pass",
        )

        response = self.submit_parking(user, self.other_worker)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Your account is not linked to an active worker profile.")
        self.assertFalse(ParkingEntry.objects.exists())


class ParkingEntryAdminReceiptTests(TestCase):
    def setUp(self):
        self.media_dir = tempfile.mkdtemp()
        self.override = override_settings(MEDIA_ROOT=self.media_dir)
        self.override.enable()
        self.addCleanup(self.override.disable)
        self.addCleanup(shutil.rmtree, self.media_dir)

        self.admin_user = User.objects.create_user(
            username="admin@example.com",
            email="admin@example.com",
            password="pass",
            is_staff=True,
        )
        self.worker = Worker.objects.create(
            display_name="A Worker",
            email="worker@example.com",
        )
        self.project = Project.objects.create(name="A Project")

    def test_admin_receipt_route_streams_uploaded_file(self):
        entry = ParkingEntry.objects.create(
            worker=self.worker,
            project=self.project,
            work_date=date(2026, 6, 6),
            amount=Decimal("12.50"),
            submitted_by=self.admin_user,
            receipt=SimpleUploadedFile(
                "receipt.jpeg",
                b"receipt-bytes",
                content_type="image/jpeg",
            ),
        )
        self.client.force_login(self.admin_user)

        response = self.client.get(reverse("admin:core_parkingentry_receipt", args=[entry.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(b"".join(response.streaming_content), b"receipt-bytes")

    def test_admin_receipt_download_route_sends_attachment(self):
        entry = ParkingEntry.objects.create(
            worker=self.worker,
            project=self.project,
            work_date=date(2026, 6, 6),
            amount=Decimal("12.50"),
            submitted_by=self.admin_user,
            receipt=SimpleUploadedFile(
                "receipt.jpeg",
                b"receipt-bytes",
                content_type="image/jpeg",
            ),
        )
        self.client.force_login(self.admin_user)

        response = self.client.get(reverse("admin:core_parkingentry_receipt_download", args=[entry.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(b"".join(response.streaming_content), b"receipt-bytes")
        self.assertIn("attachment", response["Content-Disposition"])
        self.assertIn("receipt.jpeg", response["Content-Disposition"])

    def test_admin_receipt_link_uses_protected_admin_route(self):
        entry = ParkingEntry.objects.create(
            worker=self.worker,
            project=self.project,
            work_date=date(2026, 6, 6),
            amount=Decimal("12.50"),
            submitted_by=self.admin_user,
            receipt=SimpleUploadedFile(
                "receipt.jpeg",
                b"receipt-bytes",
                content_type="image/jpeg",
            ),
        )
        self.client.force_login(self.admin_user)

        response = self.client.get(reverse("admin:core_parkingentry_changelist"))

        expected_url = reverse("admin:core_parkingentry_receipt", args=[entry.pk])
        expected_download_url = reverse("admin:core_parkingentry_receipt_download", args=[entry.pk])
        self.assertContains(response, expected_url)
        self.assertContains(
            response,
            f'<a href="{expected_url}" target="_blank" rel="noopener noreferrer">',
        )
        self.assertContains(response, expected_download_url)
        self.assertContains(response, "Download")
        self.assertNotContains(response, "/media/parking_receipts/")

    def test_admin_change_form_receipt_widget_uses_protected_admin_route(self):
        entry = ParkingEntry.objects.create(
            worker=self.worker,
            project=self.project,
            work_date=date(2026, 6, 6),
            amount=Decimal("12.50"),
            submitted_by=self.admin_user,
            receipt=SimpleUploadedFile(
                "receipt.jpeg",
                b"receipt-bytes",
                content_type="image/jpeg",
            ),
        )
        self.client.force_login(self.admin_user)

        response = self.client.get(reverse("admin:core_parkingentry_change", args=[entry.pk]))

        expected_url = reverse("admin:core_parkingentry_receipt", args=[entry.pk])
        expected_download_url = reverse("admin:core_parkingentry_receipt_download", args=[entry.pk])
        self.assertContains(response, expected_url)
        self.assertContains(response, expected_download_url)
        self.assertContains(response, "Download")
        self.assertNotContains(response, "/media/parking_receipts/")
