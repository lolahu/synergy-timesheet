from django.db import migrations


def sync_username_to_email(apps, schema_editor):
    User = apps.get_model("auth", "User")
    Worker = apps.get_model("core", "Worker")

    for user in User.objects.exclude(email=""):
        email = user.email.strip().lower()
        user.email = email
        user.username = email
        user.save(update_fields=["email", "username"])

        Worker.objects.filter(user=user).update(email=email, is_active=user.is_active)


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0009_simplify_user_roles"),
    ]

    operations = [
        migrations.RunPython(sync_username_to_email, migrations.RunPython.noop),
    ]
