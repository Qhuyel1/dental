from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="DatabaseBackup",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("file_name", models.CharField(max_length=180, unique=True, verbose_name="Tên tệp")),
                ("size_bytes", models.PositiveBigIntegerField(default=0, verbose_name="Dung lượng")),
                ("note", models.CharField(blank=True, max_length=255, verbose_name="Ghi chú")),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True, verbose_name="Thời điểm tạo")),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="database_backups",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Người tạo",
                    ),
                ),
            ],
            options={
                "verbose_name": "Bản sao lưu dữ liệu",
                "verbose_name_plural": "Bản sao lưu dữ liệu",
                "ordering": ["-created_at"],
                "permissions": [("download_databasebackup", "Có thể tải bản sao lưu dữ liệu")],
            },
        ),
        migrations.CreateModel(
            name="SecurityEvent",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "username",
                    models.CharField(blank=True, max_length=150, verbose_name="Tên đăng nhập"),
                ),
                (
                    "action",
                    models.CharField(
                        choices=[
                            ("login_success", "Đăng nhập thành công"),
                            ("login_failed", "Đăng nhập thất bại"),
                            ("logout", "Đăng xuất"),
                            ("password_change", "Đổi mật khẩu"),
                            ("create", "Tạo dữ liệu"),
                            ("update", "Cập nhật dữ liệu"),
                            ("delete", "Xóa dữ liệu"),
                            ("backup_created", "Tạo bản sao lưu"),
                            ("backup_downloaded", "Tải bản sao lưu"),
                            ("backup_failed", "Sao lưu thất bại"),
                            ("access_denied", "Từ chối truy cập"),
                        ],
                        db_index=True,
                        max_length=40,
                        verbose_name="Hành động",
                    ),
                ),
                ("target_app", models.CharField(blank=True, max_length=80, verbose_name="Ứng dụng")),
                ("target_model", models.CharField(blank=True, max_length=80, verbose_name="Đối tượng")),
                ("target_object_id", models.CharField(blank=True, max_length=80, verbose_name="ID đối tượng")),
                ("target_repr", models.CharField(blank=True, max_length=255, verbose_name="Mô tả đối tượng")),
                ("request_method", models.CharField(blank=True, max_length=10, verbose_name="Phương thức")),
                ("path", models.CharField(blank=True, max_length=255, verbose_name="Đường dẫn")),
                ("ip_address", models.GenericIPAddressField(blank=True, null=True, verbose_name="IP")),
                ("user_agent", models.CharField(blank=True, max_length=255, verbose_name="User agent")),
                ("message", models.TextField(blank=True, verbose_name="Ghi chú")),
                ("metadata", models.JSONField(blank=True, default=dict, verbose_name="Dữ liệu bổ sung")),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True, verbose_name="Thời điểm")),
                (
                    "actor",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="security_events",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Người thực hiện",
                    ),
                ),
            ],
            options={
                "verbose_name": "Nhật ký thao tác",
                "verbose_name_plural": "Nhật ký thao tác",
                "ordering": ["-created_at"],
                "permissions": [
                    ("view_dashboard", "Có thể xem dashboard hệ thống"),
                    ("run_database_backup", "Có thể tạo bản sao lưu dữ liệu"),
                ],
            },
        ),
    ]
