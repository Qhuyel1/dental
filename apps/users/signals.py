from django.contrib.auth import get_user_model
from django.contrib.auth.signals import user_logged_in, user_logged_out, user_login_failed
from django.db.models.signals import post_migrate, post_save
from django.dispatch import receiver

from .models import SecurityEvent, UserSecurityProfile
from .roles import sync_role_groups


User = get_user_model()


@receiver(user_logged_in)
def log_user_logged_in(sender, request, user, **kwargs):
    SecurityEvent.record(
        SecurityEvent.Action.LOGIN_SUCCESS,
        request=request,
        actor=user,
        message="Đăng nhập vào hệ thống.",
    )


@receiver(user_login_failed)
def log_user_login_failed(sender, credentials, request, **kwargs):
    username = credentials.get("username", "")
    SecurityEvent.record(
        SecurityEvent.Action.LOGIN_FAILED,
        request=request,
        username=username,
        message="Đăng nhập thất bại.",
    )


@receiver(user_logged_out)
def log_user_logged_out(sender, request, user, **kwargs):
    SecurityEvent.record(
        SecurityEvent.Action.LOGOUT,
        request=request,
        actor=user,
        message="Đăng xuất khỏi hệ thống.",
    )


@receiver(post_migrate, dispatch_uid="apps.users.sync_role_groups")
def sync_default_roles(sender, using, **kwargs):
    sync_role_groups(using=using)


@receiver(post_save, sender=User, dispatch_uid="apps.users.ensure_security_profile")
def ensure_user_security_profile(sender, instance, created, **kwargs):
    if created:
        UserSecurityProfile.objects.get_or_create(user=instance)
