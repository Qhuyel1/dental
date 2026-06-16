from django.urls import path

from .views import (
    DatabaseBackupDownloadView,
    DatabaseBackupListView,
    SecurityEventListView,
    SystemLoginView,
    SystemLogoutView,
    SystemPasswordChangeDoneView,
    SystemPasswordChangeView,
    UserCreateView,
    UserDeleteView,
    UserListView,
    UserPasswordResetView,
    UserUpdateView,
)

app_name = "users"

urlpatterns = [
    path("login/", SystemLoginView.as_view(), name="login"),
    path("logout/", SystemLogoutView.as_view(), name="logout"),
    path("password/change/", SystemPasswordChangeView.as_view(), name="password-change"),
    path("password/change/done/", SystemPasswordChangeDoneView.as_view(), name="password-change-done"),
    path("activity-log/", SecurityEventListView.as_view(), name="security-event-list"),
    path("backups/", DatabaseBackupListView.as_view(), name="backup-list"),
    path("backups/<int:pk>/download/", DatabaseBackupDownloadView.as_view(), name="backup-download"),
    path("", UserListView.as_view(), name="user-list"),
    path("create/", UserCreateView.as_view(), name="user-create"),
    path("<int:pk>/edit/", UserUpdateView.as_view(), name="user-update"),
    path("<int:pk>/reset-password/", UserPasswordResetView.as_view(), name="user-reset-password"),
    path("<int:pk>/delete/", UserDeleteView.as_view(), name="user-delete"),
]
