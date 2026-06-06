from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import Project, TimeEntry, Worker
from .permissions import can_enter_for_others, user_is_foreman


User = get_user_model()


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
