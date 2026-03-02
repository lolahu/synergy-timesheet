from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

# ── Branding ──────────────────────────────────────────────────────────────────
admin.site.site_header = "Synergy Timesheet Administration"
admin.site.site_title  = "Synergy Timesheet Admin"
admin.site.index_title = "Dashboard"
# ─────────────────────────────────────────────────────────────────────────────

User = get_user_model()

admin.site.unregister(User)


@admin.register(User)
class UserAdmin(DjangoUserAdmin):

    # 🔹 Add Role column
    list_display = (
        "username",
        "email",
        "role_display",
        "is_active",
    )

    search_fields = ("username", "email")
    list_filter = ("is_active", "is_staff", "is_superuser", "groups")

    fieldsets = (
        ("Account", {"fields": ("username", "email", "password")}),
        ("Roles (use Groups)", {"fields": ("groups",)}),
        ("Admin site access", {"fields": ("is_staff",)}),
        ("Account status", {"fields": ("is_active",)}),
        ("Superuser (rare)", {"fields": ("is_superuser",)}),
        ("Important dates", {"fields": ("last_login", "date_joined")}),
    )

    add_fieldsets = (
        ("Account", {"classes": ("wide",), "fields": ("username", "email", "password1", "password2")}),
        ("Roles (use Groups)", {"classes": ("wide",), "fields": ("groups",)}),
        ("Access", {"classes": ("wide",), "fields": ("is_staff", "is_active")}),
        ("Superuser (rare)", {"classes": ("wide",), "fields": ("is_superuser",)}),
    )

    # 🔹 Custom role logic
    def role_display(self, obj):
        if obj.is_superuser:
            return "👑 Superuser"
        if obj.is_staff:
            return "🛠 Admin"
        if obj.groups.filter(name="FOREMAN").exists():
            return "👷‍♂️ Foreman"
        if hasattr(obj, "worker_profile"):
            return "👷 Worker"
        return "—"

    role_display.short_description = "Role"