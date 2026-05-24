from django.conf import settings


DEFAULT_FOREMAN_GROUP_NAME = "Foreman"


def foreman_group_name() -> str:
    return getattr(settings, "FOREMAN_GROUP_NAME", DEFAULT_FOREMAN_GROUP_NAME)


def user_is_foreman(user) -> bool:
    if not getattr(user, "is_authenticated", False):
        return False
    return user.groups.filter(name__iexact=foreman_group_name()).exists()


def can_enter_for_others(user) -> bool:
    return getattr(user, "is_staff", False) or user_is_foreman(user)
