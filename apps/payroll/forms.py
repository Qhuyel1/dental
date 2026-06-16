from decimal import Decimal

from django import forms
from django.utils import timezone

from apps.clinic.models import Appointment, Staff

from .models import AppointmentComplexity, PaySlip, SalaryConfig


class FormControlMixin:
    """Áp dụng class Bootstrap-style cho tất cả input."""

    def apply_common_attrs(self):
        for field in self.fields.values():
            widget = field.widget
            if isinstance(widget, (forms.TextInput, forms.NumberInput, forms.EmailInput,
                                   forms.URLInput, forms.PasswordInput, forms.DateInput,
                                   forms.TimeInput, forms.DateTimeInput, forms.Textarea,
                                   forms.Select)):
                existing = widget.attrs.get("class", "")
                widget.attrs["class"] = (existing + " form-control").strip()
            elif isinstance(widget, forms.CheckboxInput):
                existing = widget.attrs.get("class", "")
                widget.attrs["class"] = (existing + " form-check-input").strip()


# ─── UC4.1 Cấu hình lương cơ bản ────────────────────────────────────────────

class SalaryConfigForm(FormControlMixin, forms.ModelForm):
    class Meta:
        model = SalaryConfig
        fields = ["hourly_rate", "effective_from", "note"]
        widgets = {
            "hourly_rate": forms.NumberInput(attrs={"min": 0, "step": 1000}),
            "effective_from": forms.DateInput(attrs={"type": "date"}),
            "note": forms.Textarea(attrs={"rows": 3}),
        }
        help_texts = {
            "hourly_rate": "Nhập số tiền VNĐ cho 1 giờ quy đổi. Ví dụ: 150000.",
            "effective_from": "Cấu hình này được áp dụng khi lập phiếu lương từ ngày này.",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.apply_common_attrs()


# ─── UC4.3 Nhập hệ số ca phức tạp ──────────────────────────────────────────

class AppointmentComplexityForm(FormControlMixin, forms.ModelForm):
    class Meta:
        model = AppointmentComplexity
        fields = ["appointment", "complexity_coefficient", "note"]
        widgets = {
            "complexity_coefficient": forms.NumberInput(
                attrs={"min": "0.00", "max": "0.50", "step": "0.01"}
            ),
        }

    def __init__(self, *args, appointment=None, **kwargs):
        super().__init__(*args, **kwargs)
        if appointment:
            self.fields["appointment"].initial = appointment
            self.fields["appointment"].required = False
            self.fields["appointment"].widget = forms.HiddenInput()
        else:
            self.fields["appointment"].queryset = (
                Appointment.objects.select_related(
                    "patient", "doctor_schedule__doctor"
                )
                .exclude(status=Appointment.Status.CANCELLED)
                .order_by("-doctor_schedule__work_date", "patient__full_name")
            )
        self.apply_common_attrs()


# ─── UC4.4 Lập phiếu lương ───────────────────────────────────────────────────

class PaySlipGenerateForm(FormControlMixin, forms.Form):
    doctor = forms.ModelChoiceField(
        label="Bác sĩ",
        queryset=Staff.objects.filter(role=Staff.Role.DOCTOR, is_active=True).order_by("full_name"),
        help_text="Chọn bác sĩ cần lập phiếu lương.",
    )
    month = forms.IntegerField(
        label="Tháng",
        min_value=1,
        max_value=12,
        initial=timezone.localdate().month,
        widget=forms.NumberInput(attrs={"min": 1, "max": 12}),
    )
    year = forms.IntegerField(
        label="Năm",
        min_value=2000,
        max_value=2100,
        initial=timezone.localdate().year,
        widget=forms.NumberInput(attrs={"min": 2000, "max": 2100}),
    )
    note = forms.CharField(
        label="Ghi chú",
        required=False,
        widget=forms.Textarea(attrs={"rows": 3}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.apply_common_attrs()

    def clean(self):
        cleaned_data = super().clean()
        doctor = cleaned_data.get("doctor")
        month = cleaned_data.get("month")
        year = cleaned_data.get("year")
        if doctor and month and year:
            if PaySlip.objects.filter(doctor=doctor, month=month, year=year).exists():
                raise forms.ValidationError(
                    f"Phiếu lương tháng {month:02d}/{year} của bác sĩ "
                    f"{doctor.full_name} đã tồn tại. Vui lòng xóa hoặc cập nhật."
                )
        return cleaned_data


class PaySlipStatusForm(FormControlMixin, forms.ModelForm):
    class Meta:
        model = PaySlip
        fields = ["status", "note"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.apply_common_attrs()
