from django.contrib.auth.models import Group

from apps.users.roles import ROLE_PATIENT, sync_role_groups

from .staff_accounts import build_available_username, generate_initial_password


PATIENT_GROUP_NAME = ROLE_PATIENT


def sync_patient_user_access(patient):
    if not patient.user_id:
        return

    sync_role_groups()
    group, _ = Group.objects.get_or_create(name=PATIENT_GROUP_NAME)
    patient.user.groups.set([group])
