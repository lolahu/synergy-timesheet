from django.conf import settings
from django.db import migrations


def simplify_user_roles(apps, schema_editor):
    User = apps.get_model("auth", "User")
    Group = apps.get_model("auth", "Group")

    foreman_group_name = getattr(settings, "FOREMAN_GROUP_NAME", "Foreman")
    foreman_groups = Group.objects.filter(name__iexact=foreman_group_name)

    User.objects.filter(is_superuser=True).update(is_superuser=False)

    if foreman_groups.exists():
        for user in User.objects.filter(is_staff=True, groups__in=foreman_groups).distinct():
            user.groups.remove(*foreman_groups)


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0008_delete_accessrequest"),
    ]

    operations = [
        migrations.RunPython(simplify_user_roles, migrations.RunPython.noop),
    ]
