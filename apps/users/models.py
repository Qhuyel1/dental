import ipaddress
from pathlib import Path

from django.conf import settings
from django.db import models


def get_client_ip(request):
    if not request:
        return ""
    forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded_for:
        value = forwarded_for.split(",", 1)[0].strip()
    else:
        value = request.META.get("REMOTE_ADDR", "")
    try:
        ipaddress.ip_address(value)
    except ValueError:
        return ""
    return value


class SecurityEvent(models.Model):
    class Action(models.TextChoices):
        LOGIN_SUCCESS = "login_success", "Đăng nhập thành công"
        LOGIN_FAILED = "login_failed", "Đăng nhập thất bại"
        LOGOUT = "logout", "Đăng xuất"
        PASSWORD_CHANGE = "password_change", "Đổi mật khẩu"
        CREATE = "create", "Tạo dữ liệu"
        UPDATE = "update", "Cập nhật dữ liệu"
        DELETE = "delete", "Xóa dữ liệu"
        BACKUP_CREATED = "backup_created", "Tạo bản sao lưu"
        BACKUP_DOWNLOADED = "backup_downloaded", "Tải bản sao lưu"
        BACKUP_FAILED = "backup_failed", "Sao lưu thất bại"
        ACCESS_DENIED = "access_denied", "Từ chối truy cập"

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="Người thực hiện",
        blank=True,
        null=True,
        on_delete=models.SET_NULL,
        related_name="security_events",
    )
    username = models.CharField("Tên đăng nhập", max_length=150, blank=True)
    action = models.CharField("Hành động", max_length=40, choices=Action.choices, db_index=True)
    target_app = models.CharField("Ứng dụng", max_length=80, blank=True)
    target_model = models.CharField("Đối tượng", max_length=80, blank=True)
    target_object_id = models.CharField("ID đối tượng", max_length=80, blank=True)
    target_repr = models.CharField("Mô tả đối tượng", max_length=255, blank=True)
    request_method = models.CharField("Phương thức", max_length=10, blank=True)
    path = models.CharField("Đường dẫn", max_length=255, blank=True)
    ip_address = models.GenericIPAddressField("IP", blank=True, null=True)
    user_agent = models.CharField("User agent", max_length=255, blank=True)
    message = models.TextField("Ghi chú", blank=True)
    metadata = models.JSONField("Dữ liệu bổ sung", blank=True, default=dict)
    created_at = models.DateTimeField("Thời điểm", auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Nhật ký thao tác"
        verbose_name_plural = "Nhật ký thao tác"
        permissions = [
            ("view_dashboard", "Có thể xem dashboard hệ thống"),
            ("view_support_conversation", "Có thể xem hội thoại hỗ trợ"),
            ("manage_support_conversation", "Có thể xử lý hội thoại hỗ trợ"),
            ("view_payroll", "Có thể xem tính lương"),
            ("manage_payroll", "Có thể quản lý tính lương"),
            ("run_database_backup", "Có thể tạo bản sao lưu dữ liệu"),
        ]

    def __str__(self):
        actor = self.actor.get_username() if self.actor else self.username or "Ẩn danh"
        return f"{self.get_action_display()} - {actor} - {self.created_at:%d/%m/%Y %H:%M}"

    @classmethod
    def record(
        cls,
        action,
        request=None,
        actor=None,
        username="",
        target=None,
        message="",
        metadata=None,
    ):
        actor = actor or getattr(request, "user", None)
        if actor is not None and not getattr(actor, "is_authenticated", False):
            actor = None
        if not username and actor:
            username = actor.get_username()

        target_app = ""
        target_model = ""
        target_object_id = ""
        target_repr = ""
        if target is not None:
            meta = target._meta
            target_app = meta.app_label
            target_model = meta.verbose_name
            target_object_id = str(getattr(target, "pk", "") or "")
            target_repr = str(target)[:255]

        ip_address = get_client_ip(request)
        request_method = (getattr(request, "method", "") or "") if request else ""
        path = (getattr(request, "path", "") or "")[:255] if request else ""
        user_agent = (request.META.get("HTTP_USER_AGENT", "") or "")[:255] if request else ""

        return cls.objects.create(
            actor=actor,
            username=username or "",
            action=action,
            target_app=target_app,
            target_model=target_model,
            target_object_id=target_object_id,
            target_repr=target_repr,
            request_method=request_method,
            path=path,
            ip_address=ip_address or None,
            user_agent=user_agent,
            message=message,
            metadata=metadata or {},
        )


class DatabaseBackup(models.Model):
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="Người tạo",
        blank=True,
        null=True,
        on_delete=models.SET_NULL,
        related_name="database_backups",
    )
    file_name = models.CharField("Tên tệp", max_length=180, unique=True)
    size_bytes = models.PositiveBigIntegerField("Dung lượng", default=0)
    note = models.CharField("Ghi chú", max_length=255, blank=True)
    created_at = models.DateTimeField("Thời điểm tạo", auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Bản sao lưu dữ liệu"
        verbose_name_plural = "Bản sao lưu dữ liệu"
        permissions = [
            ("download_databasebackup", "Có thể tải bản sao lưu dữ liệu"),
        ]

    def __str__(self):
        return self.file_name

    @property
    def absolute_path(self):
        return Path(settings.BACKUP_ROOT) / self.file_name

    @property
    def exists_on_disk(self):
        return self.absolute_path.exists()

    @property
    def size_display(self):
        size = self.size_bytes or 0
        if size >= 1024 * 1024:
            return f"{size / (1024 * 1024):.1f} MB"
        if size >= 1024:
            return f"{size / 1024:.1f} KB"
        return f"{size} B"


class UserSecurityProfile(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="security_profile",
        verbose_name="Người dùng",
    )
    must_change_password = models.BooleanField("Bắt buộc đổi mật khẩu", default=False)
    created_at = models.DateTimeField("Ngày tạo", auto_now_add=True)
    updated_at = models.DateTimeField("Ngày cập nhật", auto_now=True)

    class Meta:
        verbose_name = "Hồ sơ bảo mật người dùng"
        verbose_name_plural = "Hồ sơ bảo mật người dùng"

    def __str__(self):
        return f"Bảo mật - {self.user.get_username()}"


def get_user_security_profile(user):
    if user is None:
        return None
    return UserSecurityProfile.objects.get_or_create(user=user)[0]
