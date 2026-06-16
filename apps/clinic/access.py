from .models import Staff


def get_staff_profile(user):
    if not getattr(user, "is_authenticated", False):
        return None
    return getattr(user, "staff_profile", None)


def get_doctor_profile(user):
    staff = get_staff_profile(user)
    if staff and staff.role == Staff.Role.DOCTOR:
        return staff
    return None


def is_doctor_user(user):
    return get_doctor_profile(user) is not None
