from django.contrib import admin

from .models import DatabaseBackup, SecurityEvent


@admin.register(SecurityEvent)
class SecurityEventAdmin(admin.ModelAdmin):
    list_display = ("created_at", "action", "username", "target_model", "target_repr", "ip_address")
    list_filter = ("action", "target_app", "target_model", "created_at")
    search_fields = ("username", "target_repr", "message", "path", "ip_address")
    readonly_fields = [field.name for field in SecurityEvent._meta.fields]

    def has_add_permission(self, request):
        return False


@admin.register(DatabaseBackup)
class DatabaseBackupAdmin(admin.ModelAdmin):
    list_display = ("created_at", "file_name", "created_by", "size_bytes")
    list_filter = ("created_at",)
    search_fields = ("file_name", "created_by__username", "note")
