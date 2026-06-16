from django import forms
from django.contrib.auth.forms import AuthenticationForm, PasswordChangeForm, UserCreationForm
from django.contrib.auth.models import Group, User

from .roles import ROLE_ADMIN


class FormControlMixin:
    def apply_common_attrs(self):
        for field_name, field in self.fields.items():
            widget = field.widget
            if isinstance(widget, forms.CheckboxInput):
                widget.attrs.setdefault("class", "checkbox-input")
            elif isinstance(widget, forms.CheckboxSelectMultiple):
                pass
            else:
                widget.attrs.setdefault("class", "form-control")
            if field.required:
                widget.attrs.setdefault("aria-required", "true")


class UserCreateForm(FormControlMixin, UserCreationForm):
    email = forms.EmailField(label="Email", required=False)
    first_name = forms.CharField(label="Tên", max_length=150, required=False)
    last_name = forms.CharField(label="Họ", max_length=150, required=False)
    groups = forms.ModelMultipleChoiceField(
        label="Nhóm quyền",
        queryset=Group.objects.exclude(name=ROLE_ADMIN),
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )

    class Meta(UserCreationForm.Meta):
        model = User
        fields = [
            "username",
            "first_name",
            "last_name",
            "email",
            "password1",
            "password2",
            "is_active",
            "is_staff",
            "groups",
        ]
        labels = {
            "username": "Tên đăng nhập",
            "is_active": "Đang hoạt động",
            "is_staff": "Có quyền truy cập quản trị",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.apply_common_attrs()

    def save(self, commit=True):
        user = super().save(commit=commit)
        if commit:
            self.save_m2m()
        return user


class UserUpdateForm(FormControlMixin, forms.ModelForm):
    groups = forms.ModelMultipleChoiceField(
        label="Nhóm quyền",
        queryset=Group.objects.exclude(name=ROLE_ADMIN),
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )

    class Meta:
        model = User
        fields = [
            "username",
            "first_name",
            "last_name",
            "email",
            "is_active",
            "is_staff",
            "groups",
        ]
        labels = {
            "username": "Tên đăng nhập",
            "first_name": "Tên",
            "last_name": "Họ",
            "email": "Email",
            "is_active": "Đang hoạt động",
            "is_staff": "Có quyền truy cập quản trị",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.apply_common_attrs()


class LoginForm(FormControlMixin, AuthenticationForm):
    username = forms.CharField(label="Tên đăng nhập")
    password = forms.CharField(label="Mật khẩu", strip=False, widget=forms.PasswordInput)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.apply_common_attrs()


class UserPasswordChangeForm(FormControlMixin, PasswordChangeForm):
    old_password = forms.CharField(label="Mật khẩu hiện tại", strip=False, widget=forms.PasswordInput)
    new_password1 = forms.CharField(label="Mật khẩu mới", strip=False, widget=forms.PasswordInput)
    new_password2 = forms.CharField(label="Xác nhận mật khẩu mới", strip=False, widget=forms.PasswordInput)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.apply_common_attrs()
