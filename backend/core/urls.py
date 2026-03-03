from django.urls import path
from django.contrib.auth import views as auth_views
from . import views

urlpatterns = [
    path("", views.home, name="home"),

    # Auth
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),
    path("signup/", views.signup_view, name="signup"),

    # Password reset (built-in Django views, styled with our templates)
    path("password-reset/",
        auth_views.PasswordResetView.as_view(
            template_name="core/password_reset.html",
            email_template_name="core/password_reset_email.txt",
            subject_template_name="core/password_reset_subject.txt",
        ),
        name="password_reset",
    ),
    path("password-reset/done/",
        auth_views.PasswordResetDoneView.as_view(
            template_name="core/password_reset_done.html",
        ),
        name="password_reset_done",
    ),
    path("password-reset/<uidb64>/<token>/",
        auth_views.PasswordResetConfirmView.as_view(
            template_name="core/password_reset_confirm.html",
        ),
        name="password_reset_confirm",
    ),
    path("password-reset/complete/",
        auth_views.PasswordResetCompleteView.as_view(
            template_name="core/password_reset_complete.html",
        ),
        name="password_reset_complete",
    ),

    # Timesheet
    path("timesheet/success/", views.timesheet_success, name="timesheet_success"),
    path("timesheet/", views.timesheet_weekly, name="timesheet"),

    # Parking
    path("parking/success/", views.parking_success, name="parking_success"),
    path("parking/", views.parking_entry, name="parking_entry"),
]
