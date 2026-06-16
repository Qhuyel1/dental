from django.contrib import messages
from django.conf import settings
from django.contrib.auth import views as auth_views
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.models import User
from django.core.management import call_command
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.utils.crypto import get_random_string
from django.views import View
from django.views.generic import CreateView, DeleteView, ListView, UpdateView

from core.mixins import StaffRequiredMixin

from .forms import LoginForm, UserCreateForm, UserPasswordChangeForm, UserUpdateForm
from .models import DatabaseBackup, SecurityEvent, get_user_security_profile


LIST_PAGE_SIZE = 10


def get_pagination_query(request):
    query = request.GET.copy()
    query.pop("page", None)
    return query.urlencode()


class UserListView(StaffRequiredMixin, ListView):
    model = User
    template_name = "users/user_list.html"
    context_object_name = "users"
    paginate_by = LIST_PAGE_SIZE

    def get_queryset(self):
        queryset = User.objects.select_related("staff_profile", "patient_profile").prefetch_related("groups").order_by("username")
        keyword = self.request.GET.get("q", "").strip()
        account_type = self.request.GET.get("type", "").strip()

        if keyword:
            queryset = queryset.filter(
                Q(username__icontains=keyword)
                | Q(first_name__icontains=keyword)
                | Q(last_name__icontains=keyword)
                | Q(email__icontains=keyword)
                | Q(staff_profile__full_name__icontains=keyword)
                | Q(staff_profile__employee_code__icontains=keyword)
                | Q(patient_profile__full_name__icontains=keyword)
                | Q(patient_profile__patient_code__icontains=keyword)
            )

        if account_type == "staff":
            queryset = queryset.filter(staff_profile__isnull=False)
        elif account_type == "patient":
            queryset = queryset.filter(patient_profile__isnull=False)
        elif account_type == "unlinked":
            queryset = queryset.filter(staff_profile__isnull=True, patient_profile__isnull=True)

        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["keyword"] = self.request.GET.get("q", "").strip()
        context["selected_type"] = self.request.GET.get("type", "").strip()
        context["pagination_query"] = get_pagination_query(self.request)
        return context


class UserCreateView(StaffRequiredMixin, CreateView):
    model = User
    form_class = UserCreateForm
    template_name = "users/user_form.html"
    success_url = reverse_lazy("users:user-list")

    def form_valid(self, form):
        messages.success(self.request, "Đã tạo người dùng.")
        return super().form_valid(form)


class UserUpdateView(StaffRequiredMixin, UpdateView):
    model = User
    form_class = UserUpdateForm
    template_name = "users/user_form.html"
    success_url = reverse_lazy("users:user-list")

    def form_valid(self, form):
        if self.object == self.request.user:
            if not form.cleaned_data.get("is_active"):
                form.add_error("is_active", "Không thể tự khóa tài khoản đang đăng nhập.")
                return self.form_invalid(form)
            if not form.cleaned_data.get("is_staff"):
                form.add_error("is_staff", "Không thể tự gỡ quyền truy cập quản trị của chính mình.")
                return self.form_invalid(form)
        messages.success(self.request, "Đã cập nhật người dùng.")
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        credential_notice = self.request.session.get("reset_user_credentials")
        if credential_notice and credential_notice.get("user_id") == self.object.pk:
            context["reset_credentials"] = credential_notice
            del self.request.session["reset_user_credentials"]
            self.request.session.modified = True
        return context


class UserDeleteView(StaffRequiredMixin, DeleteView):
    model = User
    template_name = "users/user_confirm_delete.html"
    success_url = reverse_lazy("users:user-list")

    def form_valid(self, form):
        if self.get_object() == self.request.user:
            messages.error(self.request, "Không thể tự xóa tài khoản đang đăng nhập.")
            return redirect(self.success_url)
        messages.success(self.request, "Đã xóa người dùng.")
        return super().form_valid(form)


class UserPasswordResetView(StaffRequiredMixin, View):
    permission_required = "auth.change_user"

    def post(self, request, *args, **kwargs):
        user = get_object_or_404(User, pk=kwargs["pk"])
        temporary_password = get_random_string(
            length=10,
            allowed_chars="ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789",
        )
        user.set_password(temporary_password)
        user.is_active = True
        user.save(update_fields=["password", "is_active"])

        profile = get_user_security_profile(user)
        profile.must_change_password = True
        profile.save(update_fields=["must_change_password", "updated_at"])

        request.session["reset_user_credentials"] = {
            "user_id": user.pk,
            "username": user.username,
            "password": temporary_password,
        }
        messages.warning(
            request,
            "Đã đặt lại mật khẩu tạm thời. Mật khẩu mới chỉ hiển thị một lần ở màn hình cập nhật người dùng.",
        )
        return redirect("users:user-update", pk=user.pk)


class SystemLoginView(auth_views.LoginView):
    template_name = "users/login.html"
    authentication_form = LoginForm
    redirect_authenticated_user = True

    def get(self, request, *args, **kwargs):
        if self.redirect_authenticated_user and self.request.user.is_authenticated:
            if not hasattr(self.request.user, "patient_profile"):
                return redirect(self.get_success_url())
        return super().get(request, *args, **kwargs)

    def form_valid(self, form):
        user = form.get_user()
        if hasattr(user, "patient_profile"):
            form.add_error(None, "Tài khoản này không có quyền truy cập hệ thống quản lý.")
            return self.form_invalid(form)
        return super().form_valid(form)

    def get_success_url(self):
        user = self.request.user
        profile = get_user_security_profile(user)
        if profile.must_change_password:
            return reverse("users:password-change")
        
        return super().get_success_url()


class SystemLogoutView(auth_views.LogoutView):
    next_page = reverse_lazy("users:login")


class SystemPasswordChangeView(LoginRequiredMixin, auth_views.PasswordChangeView):
    template_name = "users/password_change_form.html"
    form_class = UserPasswordChangeForm
    success_url = reverse_lazy("users:password-change-done")

    def form_valid(self, form):
        response = super().form_valid(form)
        profile = get_user_security_profile(self.request.user)
        if profile.must_change_password:
            profile.must_change_password = False
            profile.save(update_fields=["must_change_password", "updated_at"])
        SecurityEvent.record(
            SecurityEvent.Action.PASSWORD_CHANGE,
            request=self.request,
            actor=self.request.user,
            message="Người dùng đổi mật khẩu.",
        )
        messages.success(self.request, "Đã đổi mật khẩu.")
        return response

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["must_change_password"] = get_user_security_profile(self.request.user).must_change_password
        return context


class SystemPasswordChangeDoneView(LoginRequiredMixin, auth_views.PasswordChangeDoneView):
    template_name = "users/password_change_done.html"


class SecurityEventListView(StaffRequiredMixin, ListView):
    model = SecurityEvent
    template_name = "users/security_event_list.html"
    context_object_name = "events"
    paginate_by = LIST_PAGE_SIZE
    permission_required = "users.view_securityevent"

    def get_queryset(self):
        queryset = SecurityEvent.objects.select_related("actor").order_by("-created_at")
        keyword = self.request.GET.get("q", "").strip()
        action = self.request.GET.get("action", "").strip()
        if keyword:
            queryset = queryset.filter(
                Q(username__icontains=keyword)
                | Q(actor__username__icontains=keyword)
                | Q(target_model__icontains=keyword)
                | Q(target_repr__icontains=keyword)
                | Q(path__icontains=keyword)
                | Q(message__icontains=keyword)
                | Q(ip_address__icontains=keyword)
            )
        if action:
            queryset = queryset.filter(action=action)
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["keyword"] = self.request.GET.get("q", "").strip()
        context["selected_action"] = self.request.GET.get("action", "").strip()
        context["action_choices"] = SecurityEvent.Action.choices
        context["pagination_query"] = get_pagination_query(self.request)
        return context


class DatabaseBackupListView(StaffRequiredMixin, ListView):
    model = DatabaseBackup
    template_name = "users/backup_list.html"
    context_object_name = "backups"
    paginate_by = LIST_PAGE_SIZE
    permission_required = "users.view_databasebackup"

    def post(self, request, *args, **kwargs):
        if not request.user.has_perm("users.run_database_backup"):
            SecurityEvent.record(
                SecurityEvent.Action.ACCESS_DENIED,
                request=request,
                message="Người dùng không đủ quyền tạo bản sao lưu.",
                metadata={"required_permissions": ["users.run_database_backup"]},
            )
            raise PermissionDenied

        backup_dir = settings.BACKUP_ROOT
        backup_dir.mkdir(parents=True, exist_ok=True)
        timestamp = timezone.localtime().strftime("%Y%m%d-%H%M%S")
        file_name = f"dental-backup-{timestamp}.json"
        file_path = backup_dir / file_name

        try:
            with file_path.open("w", encoding="utf-8") as output:
                call_command(
                    "dumpdata",
                    "contenttypes",
                    "auth",
                    "users",
                    "clinic",
                    "records",
                    format="json",
                    indent=2,
                    natural_foreign=True,
                    natural_primary=True,
                    stdout=output,
                )
            backup = DatabaseBackup.objects.create(
                created_by=request.user,
                file_name=file_name,
                size_bytes=file_path.stat().st_size,
                note="Sao lưu thủ công từ giao diện quản trị.",
            )
            SecurityEvent.record(
                SecurityEvent.Action.BACKUP_CREATED,
                request=request,
                target=backup,
                metadata={"file_name": file_name, "size_bytes": backup.size_bytes},
            )
            messages.success(request, "Đã tạo bản sao lưu dữ liệu.")
        except Exception as exc:
            if file_path.exists():
                file_path.unlink()
            SecurityEvent.record(
                SecurityEvent.Action.BACKUP_FAILED,
                request=request,
                message=str(exc),
                metadata={"file_name": file_name},
            )
            messages.error(request, f"Không thể tạo bản sao lưu: {exc}")
        return redirect("users:backup-list")


class DatabaseBackupDownloadView(StaffRequiredMixin, View):
    permission_required = "users.download_databasebackup"

    def get(self, request, *args, **kwargs):
        backup = get_object_or_404(DatabaseBackup, pk=kwargs["pk"])
        file_path = backup.absolute_path
        if not file_path.exists():
            raise Http404("Không tìm thấy tệp sao lưu.")
        SecurityEvent.record(
            SecurityEvent.Action.BACKUP_DOWNLOADED,
            request=request,
            target=backup,
            metadata={"file_name": backup.file_name, "size_bytes": backup.size_bytes},
        )
        return FileResponse(file_path.open("rb"), as_attachment=True, filename=backup.file_name)
