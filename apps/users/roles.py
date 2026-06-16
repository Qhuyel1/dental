from django.contrib.auth.models import Group, Permission


ROLE_ADMIN = "Quản trị"
ROLE_MANAGER = "Quản lý"
ROLE_RECEPTIONIST = "Lễ tân"
ROLE_DOCTOR = "Bác sĩ"
ROLE_PATIENT = "Bệnh nhân"
ROLE_ASSISTANT = "Trợ thủ"

MANAGED_APP_LABELS = ["auth", "users", "clinic", "records"]


def model_permissions(app_label, model_name, actions=("view", "add", "change", "delete")):
    return [f"{app_label}.{action}_{model_name}" for action in actions]


def view_permissions(app_label, *model_names):
    permissions = []
    for model_name in model_names:
        permissions.extend(model_permissions(app_label, model_name, actions=("view",)))
    return permissions


def all_permissions(app_label, *model_names):
    permissions = []
    for model_name in model_names:
        permissions.extend(model_permissions(app_label, model_name))
    return permissions


SYSTEM_PERMISSIONS = [
    "users.view_dashboard",
]

USER_VIEW_PERMISSIONS = [
    "auth.view_user",
    "auth.view_group",
]

USER_MANAGEMENT_PERMISSIONS = [
    *model_permissions("auth", "user"),
    *model_permissions("auth", "group"),
]

SECURITY_ADMIN_PERMISSIONS = [
    "users.view_securityevent",
    "users.view_databasebackup",
    "users.add_databasebackup",
    "users.download_databasebackup",
    "users.delete_databasebackup",
    "users.run_database_backup",
]

SUPPORT_PERMISSIONS = [
    "users.view_support_conversation",
    "users.manage_support_conversation",
]

PAYROLL_PERMISSIONS = [
    "users.view_payroll",
    "users.manage_payroll",
]

CATALOG_MODELS = [
    "servicecategory",
    "service",
    "pricelist",
    "serviceprice",
]
STAFF_MODELS = ["staff"]
PATIENT_MODELS = ["patient"]
SCHEDULE_MODELS = ["clinicholiday", "workshift", "doctorschedule", "appointment"]
FINANCE_MODELS = ["invoice", "invoiceitem", "payment"]
MEDICAL_MODELS = ["medicine", "prescription", "prescriptionitem"]
STOCK_MODELS = ["supply", "supplylot", "supplyexport"]


ROLE_PERMISSION_LABELS = {
    ROLE_PATIENT: [],
    ROLE_MANAGER: [
        *SYSTEM_PERMISSIONS,
        *USER_VIEW_PERMISSIONS,
        *all_permissions("clinic", *STAFF_MODELS),
        *all_permissions("clinic", *CATALOG_MODELS),
        *all_permissions("clinic", *PATIENT_MODELS),
        *all_permissions("clinic", *SCHEDULE_MODELS),
        *view_permissions("clinic", *FINANCE_MODELS, *MEDICAL_MODELS),
        *all_permissions("clinic", *STOCK_MODELS),
        *SUPPORT_PERMISSIONS,
        *PAYROLL_PERMISSIONS,
    ],
    ROLE_RECEPTIONIST: [
        *SYSTEM_PERMISSIONS,
        *view_permissions("clinic", *STAFF_MODELS, *CATALOG_MODELS, *MEDICAL_MODELS),
        *all_permissions("clinic", *PATIENT_MODELS),
        *all_permissions("clinic", *SCHEDULE_MODELS),
        *all_permissions("clinic", *FINANCE_MODELS),
        *SUPPORT_PERMISSIONS,
    ],
    ROLE_DOCTOR: [
        *SYSTEM_PERMISSIONS,
        *view_permissions("clinic", *STAFF_MODELS, *CATALOG_MODELS, *SCHEDULE_MODELS),
        *model_permissions("clinic", "patient", actions=("view", "change")),
        *model_permissions("clinic", "appointment", actions=("view", "change")),
        *model_permissions("clinic", "medicine", actions=("view",)),
        *all_permissions("clinic", "prescription", "prescriptionitem"),
    ],
    ROLE_ASSISTANT: [
        *SYSTEM_PERMISSIONS,
        *view_permissions("clinic", *STAFF_MODELS, *CATALOG_MODELS, *PATIENT_MODELS, *SCHEDULE_MODELS, *MEDICAL_MODELS),
        *model_permissions("clinic", "supplyexport", actions=("view", "add", "change")),
    ],
}


def get_permissions_from_labels(labels, using="default"):
    permissions = []
    for label in labels:
        app_label, codename = label.split(".", 1)
        permission = (
            Permission.objects.using(using)
            .filter(content_type__app_label=app_label, codename=codename)
            .first()
        )
        if permission:
            permissions.append(permission)
    return permissions


def sync_role_groups(using="default"):
    admin_permissions = Permission.objects.using(using).filter(content_type__app_label__in=MANAGED_APP_LABELS)
    admin_group, _ = Group.objects.using(using).get_or_create(name=ROLE_ADMIN)
    admin_group.permissions.set(admin_permissions)

    for role_name, permission_labels in ROLE_PERMISSION_LABELS.items():
        group, _ = Group.objects.using(using).get_or_create(name=role_name)
        group.permissions.set(get_permissions_from_labels(permission_labels, using=using))
