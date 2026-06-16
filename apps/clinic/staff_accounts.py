from secrets import choice
from string import ascii_letters, digits

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group

from apps.users.roles import ROLE_ASSISTANT, ROLE_DOCTOR, ROLE_MANAGER, ROLE_RECEPTIONIST, sync_role_groups

from .models import Staff


User = get_user_model()

STAFF_ROLE_GROUPS = {
    Staff.Role.DOCTOR: ROLE_DOCTOR,
    Staff.Role.ASSISTANT: ROLE_ASSISTANT,
    Staff.Role.RECEPTIONIST: ROLE_RECEPTIONIST,
    Staff.Role.MANAGER: ROLE_MANAGER,
    Staff.Role.TECHNICIAN: ROLE_ASSISTANT,
}


def generate_initial_password(length=10):
    alphabet = ascii_letters + digits
    return "".join(choice(alphabet) for _ in range(length))


def get_group_name_for_staff_role(role):
    return STAFF_ROLE_GROUPS.get(role)


def build_available_username(base_username):
    username = (base_username or "").strip().lower()
    if not username:
        username = "staff"

    if not User.objects.filter(username__iexact=username).exists():
        return username

    suffix = 2
    while True:
        candidate = f"{username}-{suffix}"
        if not User.objects.filter(username__iexact=candidate).exists():
            return candidate
        suffix += 1


def sync_staff_user_access(staff):
    if not staff.user_id:
        return

    user = staff.user
    group_name = get_group_name_for_staff_role(staff.role)
    if group_name:
        sync_role_groups()
        group, _ = Group.objects.get_or_create(name=group_name)
        user.groups.set([group])
    else:
        user.groups.clear()
