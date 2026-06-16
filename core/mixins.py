from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.core.exceptions import PermissionDenied
from django.forms.models import model_to_dict
from django.views.generic import CreateView, DeleteView, DetailView, ListView, UpdateView


class StaffRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    permission_required = None

    def test_func(self):
        user = self.request.user
        if not user.is_authenticated:
            return False
        if user.is_superuser:
            return True
        if not user.is_staff:
            return False
        permissions = self.get_permission_required()
        if not permissions:
            return user.is_staff
        return user.has_perms(permissions)

    def handle_no_permission(self):
        if self.request.user.is_authenticated:
            self.log_access_denied()
            raise PermissionDenied
        return super().handle_no_permission()

    def get_permission_required(self):
        if self.permission_required:
            if isinstance(self.permission_required, str):
                return [self.permission_required]
            return list(self.permission_required)

        model = self.get_permission_model()
        if model is None:
            return ["users.view_dashboard"]

        action = self.get_permission_action()
        return [f"{model._meta.app_label}.{action}_{model._meta.model_name}"]

    def get_permission_action(self):
        if isinstance(self, CreateView):
            return "add"
        if isinstance(self, UpdateView):
            return "change"
        if isinstance(self, DeleteView):
            return "delete"
        if isinstance(self, (DetailView, ListView)):
            return "view"
        if self.request.method in ("POST", "PUT", "PATCH"):
            return "change"
        return "view"

    def get_permission_model(self):
        if getattr(self, "model", None) is not None:
            return self.model
        get_queryset = getattr(self, "get_queryset", None)
        if get_queryset:
            try:
                return get_queryset().model
            except Exception:
                return None
        return None

    def form_valid(self, form):
        if isinstance(self, DeleteView):
            target = self.get_object()
            metadata = {"before": self.serialize_model(target)}
            response = super().form_valid(form)
            self.log_audit_event("delete", target=target, metadata=metadata)
            return response

        before = None
        if isinstance(self, UpdateView) and getattr(form.instance, "pk", None):
            original = form.instance.__class__.objects.filter(pk=form.instance.pk).first()
            if original:
                before = self.serialize_model(original)

        response = super().form_valid(form)
        action = "update" if isinstance(self, UpdateView) else "create"
        metadata = {"after": self.serialize_model(self.object)}
        if before is not None:
            metadata["before"] = before
            metadata["changes"] = self.diff_snapshots(before, metadata["after"])
        self.log_audit_event(action, target=self.object, metadata=metadata)
        return response

    def log_audit_event(self, action, target=None, metadata=None):
        try:
            from apps.users.models import SecurityEvent

            action_map = {
                "create": SecurityEvent.Action.CREATE,
                "update": SecurityEvent.Action.UPDATE,
                "delete": SecurityEvent.Action.DELETE,
            }
            SecurityEvent.record(
                action_map[action],
                request=self.request,
                target=target,
                metadata=metadata,
            )
        except Exception:
            pass

    def log_access_denied(self):
        try:
            from apps.users.models import SecurityEvent

            SecurityEvent.record(
                SecurityEvent.Action.ACCESS_DENIED,
                request=self.request,
                message="Người dùng không đủ quyền truy cập.",
                metadata={"required_permissions": self.get_permission_required()},
            )
        except Exception:
            pass

    def serialize_model(self, instance):
        data = model_to_dict(instance)
        return {key: self.serialize_value(value) for key, value in data.items()}

    def serialize_value(self, value):
        if isinstance(value, (list, tuple)):
            return [self.serialize_value(item) for item in value]
        if isinstance(value, dict):
            return {key: self.serialize_value(item) for key, item in value.items()}
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        return str(value)

    def diff_snapshots(self, before, after):
        changes = {}
        for key in sorted(set(before) | set(after)):
            if before.get(key) != after.get(key):
                changes[key] = {"before": before.get(key), "after": after.get(key)}
        return changes
