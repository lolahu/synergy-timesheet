from django.urls import path
from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("request-access/", views.request_access, name="request_access"),
    path("login/", views.login_request, name="login_request"),
    path("magic/<str:token>/", views.magic_login, name="magic_login"),
    path("logout/", views.logout_view, name="logout"),

    # Timesheet
    path("timesheet/success/", views.timesheet_success, name="timesheet_success"),
    path("timesheet/", views.timesheet_weekly, name="timesheet"),

    # Parking
    path("parking/success/", views.parking_success, name="parking_success"),
    path("parking/", views.parking_entry, name="parking_entry"),
]