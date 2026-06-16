from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.db import transaction
from django.db.models import Q, Sum
from django.utils import timezone

from apps.users.models import get_user_security_profile

from .access import get_doctor_profile
from .patient_accounts import sync_patient_user_access
from .staff_accounts import build_available_username, generate_initial_password, sync_staff_user_access
from .models import (
    Appointment,
    ClinicHoliday,
    DoctorSchedule,
    Invoice,
    InvoiceItem,
    Medicine,
    Patient,
    Payment,
    PaymentTransaction,
    PriceList,
    Prescription,
    PrescriptionItem,
    Service,
    ServiceCategory,
    ServicePrice,
    Staff,
    Supply,
    SupplyExport,
    SupplyLot,
    WorkShift,
)

User = get_user_model()


class FormControlMixin:
    def apply_common_attrs(self):
        for field_name, field in self.fields.items():
            widget = field.widget
            if isinstance(widget, forms.CheckboxInput):
                widget.attrs.setdefault("class", "checkbox-input")
            else:
                widget.attrs.setdefault("class", "form-control")
            if field.required:
                widget.attrs.setdefault("aria-required", "true")


class PatientForm(FormControlMixin, forms.ModelForm):
    create_login_account = forms.BooleanField(
        label="Tạo tài khoản đăng nhập",
        required=False,
    )
    username = forms.CharField(
        label="Tên đăng nhập",
        max_length=150,
        required=False,
        help_text="Để trống để dùng mã bệnh nhân viết thường sau khi lưu.",
    )
    initial_password = forms.CharField(
        label="Mật khẩu khởi tạo",
        required=False,
        widget=forms.PasswordInput(render_value=True),
        help_text="Để trống để hệ thống sinh mật khẩu ngẫu nhiên 10 ký tự.",
    )

    class Meta:
        model = Patient
        fields = [
            "patient_code",
            "full_name",
            "date_of_birth",
            "gender",
            "national_id",
            "phone",
            "email",
            "address",
            "occupation",
            "emergency_contact_name",
            "emergency_contact_phone",
            "blood_type",
            "medical_history",
            "current_medications",
            "allergy_note",
            "note",
            "is_active",
        ]
        widgets = {
            "date_of_birth": forms.DateInput(attrs={"type": "date"}),
            "medical_history": forms.Textarea(attrs={"rows": 3}),
            "current_medications": forms.Textarea(attrs={"rows": 3}),
            "allergy_note": forms.Textarea(attrs={"rows": 3}),
            "note": forms.Textarea(attrs={"rows": 3}),
        }
        help_texts = {
            "patient_code": "Để trống nếu muốn hệ thống tự sinh mã.",
            "allergy_note": "Ghi rõ các loại thuốc hoặc vật liệu dị ứng nếu có.",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.apply_common_attrs()
        self.generated_user = None
        self.generated_password = ""
        self.generated_username = ""
        self.show_account_creation_fields = not bool(self.instance.pk and self.instance.user_id)
        if self.instance.pk and self.instance.user_id:
            self.fields["create_login_account"].initial = True
            self.fields["username"].initial = self.instance.user.username

    def clean_username(self):
        username = (self.cleaned_data.get("username") or "").strip().lower()
        if not username:
            return ""

        if User.objects.filter(username__iexact=username).exists():
            raise forms.ValidationError("Tên đăng nhập đã tồn tại.")
        return username

    def clean_phone(self):
        import re
        phone = (self.cleaned_data.get("phone") or "").strip()
        if phone:
            if not re.match(r"^0\d{9}$", phone):
                raise forms.ValidationError("Số điện thoại không hợp lệ (phải gồm 10 chữ số và bắt đầu bằng 0).")
        return phone

    def clean_emergency_contact_phone(self):
        import re
        phone = (self.cleaned_data.get("emergency_contact_phone") or "").strip()
        if phone:
            if not re.match(r"^0\d{9}$", phone):
                raise forms.ValidationError("Số điện thoại khẩn cấp không hợp lệ (phải gồm 10 chữ số và bắt đầu bằng 0).")
        return phone

    def clean_email(self):
        email = (self.cleaned_data.get("email") or "").strip().lower()
        if email:
            local_part = email.split("@")[0]
            if local_part.isdigit():
                raise forms.ValidationError("Phần tên trong email (trước dấu @) không được chỉ bao gồm chữ số.")
        return email

    def clean_full_name(self):
        name = self.cleaned_data.get("full_name") or ""
        name = " ".join(name.split())
        if not all(c.isalpha() or c.isspace() for c in name):
            raise forms.ValidationError("Họ và tên không được chứa số hay ký tự đặc biệt.")
        return name.title()

    def clean_date_of_birth(self):
        dob = self.cleaned_data.get("date_of_birth")
        if dob and dob > timezone.localdate():
            raise forms.ValidationError("Ngày sinh không thể lớn hơn ngày hiện tại.")
        return dob

    def clean_national_id(self):
        import re
        nid = (self.cleaned_data.get("national_id") or "").strip()
        if nid:
            if not re.match(r"^(\d{9}|\d{12})$", nid):
                raise forms.ValidationError("CCCD/CMND phải bao gồm chính xác 9 hoặc 12 chữ số.")
            qs = Patient.objects.filter(national_id=nid)
            if self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise forms.ValidationError("CCCD/CMND này đã được sử dụng cho một bệnh nhân khác.")
        return nid

    def clean(self):
        cleaned_data = super().clean()
        if not cleaned_data.get("create_login_account"):
            return cleaned_data

        if self.instance.pk and self.instance.user_id:
            return cleaned_data

        password = (cleaned_data.get("initial_password") or "").strip()
        if password:
            preview_username = cleaned_data.get("username") or cleaned_data.get("patient_code") or "patient"
            preview_user = User(
                username=preview_username,
                email=cleaned_data.get("email") or "",
                first_name=cleaned_data.get("full_name") or "",
            )
            try:
                validate_password(password, user=preview_user)
            except forms.ValidationError as exc:
                self.add_error("initial_password", exc)
        return cleaned_data

    def _create_linked_user(self, patient):
        password = (self.cleaned_data.get("initial_password") or "").strip() or generate_initial_password()
        requested_username = (self.cleaned_data.get("username") or "").strip().lower()
        username = requested_username or build_available_username(patient.patient_code.lower())

        user = User.objects.create_user(
            username=username,
            password=password,
            email=patient.email,
            first_name=patient.full_name,
            is_staff=False,
            is_active=patient.is_active,
        )
        # Patient accounts do not require mandatory password change on first login

        patient.user = user
        patient.save(update_fields=["user", "updated_at"])
        sync_patient_user_access(patient)

        self.generated_user = user
        self.generated_password = password
        self.generated_username = username

    def _sync_existing_user(self, patient):
        if not patient.user_id:
            return

        user = patient.user
        changed_fields = []
        if user.email != patient.email:
            user.email = patient.email
            changed_fields.append("email")
        if user.first_name != patient.full_name:
            user.first_name = patient.full_name
            changed_fields.append("first_name")
        if user.is_staff is not False:
            user.is_staff = False
            changed_fields.append("is_staff")
        if user.is_active != patient.is_active:
            user.is_active = patient.is_active
            changed_fields.append("is_active")
        if changed_fields:
            user.save(update_fields=changed_fields)

        sync_patient_user_access(patient)

    @transaction.atomic
    def save(self, commit=True):
        patient = super().save(commit=commit)
        if not commit:
            return patient

        if self.cleaned_data.get("create_login_account") and not patient.user_id:
            self._create_linked_user(patient)
        else:
            self._sync_existing_user(patient)
        return patient


class PatientMedicalForm(FormControlMixin, forms.ModelForm):
    class Meta:
        model = Patient
        fields = [
            "blood_type",
            "medical_history",
            "current_medications",
            "allergy_note",
            "note",
        ]
        widgets = {
            "medical_history": forms.Textarea(attrs={"rows": 3}),
            "current_medications": forms.Textarea(attrs={"rows": 3}),
            "allergy_note": forms.Textarea(attrs={"rows": 3}),
            "note": forms.Textarea(attrs={"rows": 3}),
        }
        help_texts = {
            "allergy_note": "Ghi rõ các loại thuốc hoặc vật liệu dị ứng nếu có.",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.apply_common_attrs()


class StaffForm(FormControlMixin, forms.ModelForm):
    create_login_account = forms.BooleanField(
        label="Tạo tài khoản đăng nhập",
        required=False,
    )
    username = forms.CharField(
        label="Tên đăng nhập",
        max_length=150,
        required=False,
        help_text="Để trống để dùng mã nhân viên viết thường sau khi lưu.",
    )
    initial_password = forms.CharField(
        label="Mật khẩu khởi tạo",
        required=False,
        widget=forms.PasswordInput(render_value=True),
        help_text="Để trống để hệ thống sinh mật khẩu ngẫu nhiên 10 ký tự.",
    )

    DEGREE_PRESETS = [
        ("", "--- Chọn học hàm / học vị ---"),
        ("Đại học|1.30", "Đại học — Hệ số: 1.30"),
        ("BS.CKI|1.40", "BS.CKI (Chuyên khoa I) — Hệ số: 1.40"),
        ("Thạc sĩ|1.50", "Thạc sĩ (ThS) — Hệ số: 1.50"),
        ("BS.CKII|1.60", "BS.CKII (Chuyên khoa II) — Hệ số: 1.60"),
        ("Tiến sĩ|1.70", "Tiến sĩ (TS) — Hệ số: 1.70"),
        ("PGS.TS|2.00", "Phó Giáo sư Tiến sĩ (PGS.TS) — Hệ số: 2.00"),
        ("GS.TS|2.50", "Giáo sư Tiến sĩ (GS.TS) — Hệ số: 2.50"),
        ("__custom__|0", "⚙️ Tùy chỉnh (nhập tay)"),
    ]

    degree_preset = forms.ChoiceField(
        label="Bằng cấp / Học hàm học vị",
        choices=DEGREE_PRESETS,
        required=False,
        help_text="Chọn một mục — hệ số sẽ tự điền theo. Chọn 'Üy chỉnh' nếu muốn tự nhập tay.",
    )

    class Meta:
        model = Staff
        fields = [
            "employee_code",
            "role",
            "full_name",
            "date_of_birth",
            "gender",
            "phone",
            "email",
            "address",
            "primary_workplace",
            "degree",
            "specialization",
            "license_number",
            "experience_years",
            "start_date",
            "salary_coefficient",
            "emergency_contact_name",
            "emergency_contact_phone",
            "note",
            "is_active",
        ]
        widgets = {
            "date_of_birth": forms.DateInput(attrs={"type": "date"}),
            "start_date": forms.DateInput(attrs={"type": "date"}),
            "experience_years": forms.NumberInput(attrs={"min": 0, "max": 80}),
            "salary_coefficient": forms.HiddenInput(),
            "degree": forms.HiddenInput(),
            "note": forms.Textarea(attrs={"rows": 3}),
        }
        help_texts = {
            "employee_code": "Để trống nếu muốn hệ thống tự sinh mã.",
            "specialization": "Ví dụ: Nha tổng quát, chỉnh nha, implant, nội nha.",
            "salary_coefficient": "ĐH=1.3, Thạc sĩ=1.5, Tiến sĩ=1.7, PGS=2.0, GS=2.5",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.apply_common_attrs()
        self.generated_user = None
        self.generated_password = ""
        self.generated_username = ""
        self.show_account_creation_fields = not bool(self.instance.pk and self.instance.user_id)
        if self.instance.pk and self.instance.user_id:
            self.fields["create_login_account"].initial = True
            self.fields["username"].initial = self.instance.user.username
        # Pre-select the degree preset when editing an existing staff
        if self.instance.pk and self.instance.degree:
            existing_degree = self.instance.degree
            existing_coeff = str(self.instance.salary_coefficient)
            matched = False
            for value, _ in self.DEGREE_PRESETS:
                if "|" in value:
                    preset_degree, preset_coeff = value.split("|", 1)
                    if preset_degree == existing_degree:
                        self.fields["degree_preset"].initial = value
                        matched = True
                        break
            if not matched:
                self.fields["degree_preset"].initial = "__custom__|0"

    def clean_username(self):
        username = (self.cleaned_data.get("username") or "").strip().lower()
        if not username:
            return ""

        if User.objects.filter(username__iexact=username).exists():
            raise forms.ValidationError("Tên đăng nhập đã tồn tại.")
        return username

    def clean_degree_preset(self):
        from decimal import Decimal
        preset = self.cleaned_data.get("degree_preset") or ""
        if not preset or preset == "__custom__|0":
            return preset
        if "|" in preset:
            degree_val, coeff_val = preset.split("|", 1)
            # Inject degree and salary_coefficient into cleaned_data
            self.cleaned_data["degree"] = degree_val
            try:
                self.cleaned_data["salary_coefficient"] = Decimal(coeff_val)
            except Exception:
                pass
        return preset

    def clean_phone(self):
        import re
        phone = (self.cleaned_data.get("phone") or "").strip()
        if phone:
            if not re.match(r"^0\d{9}$", phone):
                raise forms.ValidationError("Số điện thoại không hợp lệ (phải gồm 10 chữ số và bắt đầu bằng 0).")
        return phone

    def clean_emergency_contact_phone(self):
        import re
        phone = (self.cleaned_data.get("emergency_contact_phone") or "").strip()
        if phone:
            if not re.match(r"^0\d{9}$", phone):
                raise forms.ValidationError("Số điện thoại khẩn cấp không hợp lệ (phải gồm 10 chữ số và bắt đầu bằng 0).")
        return phone

    def clean_email(self):
        email = (self.cleaned_data.get("email") or "").strip().lower()
        if email:
            local_part = email.split("@")[0]
            if local_part.isdigit():
                raise forms.ValidationError("Phần tên trong email (trước dấu @) không được chỉ bao gồm chữ số.")
        return email

    def clean_salary_coefficient(self):
        val = self.cleaned_data.get("salary_coefficient")
        if val is None:
            from decimal import Decimal
            return Decimal("1.30")
        return val

    def clean_full_name(self):
        name = self.cleaned_data.get("full_name") or ""
        name = " ".join(name.split())
        if not all(c.isalpha() or c.isspace() for c in name):
            raise forms.ValidationError("Họ và tên không được chứa số hay ký tự đặc biệt.")
        return name.title()

    def clean_date_of_birth(self):
        dob = self.cleaned_data.get("date_of_birth")
        if dob:
            today = timezone.localdate()
            age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
            if age < 18:
                raise forms.ValidationError("Nhân viên phải từ đủ 18 tuổi trở lên.")
        return dob

    def clean(self):
        cleaned_data = super().clean()

        dob = cleaned_data.get("date_of_birth")
        start_date = cleaned_data.get("start_date")
        if dob and start_date:
            min_start_date = dob.replace(year=dob.year + 18)
            if start_date < min_start_date:
                self.add_error("start_date", "Ngày bắt đầu làm việc phải đảm bảo đủ 18 tuổi so với ngày sinh.")

        if not cleaned_data.get("create_login_account"):
            return cleaned_data

        if self.instance.pk and self.instance.user_id:
            return cleaned_data

        password = (cleaned_data.get("initial_password") or "").strip()
        if password:
            preview_username = cleaned_data.get("username") or cleaned_data.get("employee_code") or "staff"
            preview_user = User(
                username=preview_username,
                email=cleaned_data.get("email") or "",
                first_name=cleaned_data.get("full_name") or "",
            )
            try:
                validate_password(password, user=preview_user)
            except forms.ValidationError as exc:
                self.add_error("initial_password", exc)
        return cleaned_data

    def _create_linked_user(self, staff):
        password = (self.cleaned_data.get("initial_password") or "").strip() or generate_initial_password()
        requested_username = (self.cleaned_data.get("username") or "").strip().lower()
        username = requested_username or build_available_username(staff.employee_code.lower())

        user = User.objects.create_user(
            username=username,
            password=password,
            email=staff.email,
            first_name=staff.full_name,
            is_staff=True,
            is_active=staff.is_active,
        )
        profile = get_user_security_profile(user)
        profile.must_change_password = True
        profile.save(update_fields=["must_change_password", "updated_at"])

        staff.user = user
        staff.save(update_fields=["user", "updated_at"])
        sync_staff_user_access(staff)

        self.generated_user = user
        self.generated_password = password
        self.generated_username = username

    def _sync_existing_user(self, staff):
        if not staff.user_id:
            return

        user = staff.user
        changed_fields = []
        if user.email != staff.email:
            user.email = staff.email
            changed_fields.append("email")
        if user.first_name != staff.full_name:
            user.first_name = staff.full_name
            changed_fields.append("first_name")
        if user.is_staff is not True:
            user.is_staff = True
            changed_fields.append("is_staff")
        if user.is_active != staff.is_active:
            user.is_active = staff.is_active
            changed_fields.append("is_active")
        if changed_fields:
            user.save(update_fields=changed_fields)

        sync_staff_user_access(staff)

    @transaction.atomic
    def save(self, commit=True):
        staff = super().save(commit=commit)
        if not commit:
            return staff

        if self.cleaned_data.get("create_login_account") and not staff.user_id:
            self._create_linked_user(staff)
        else:
            self._sync_existing_user(staff)
        return staff


class ServiceCategoryForm(FormControlMixin, forms.ModelForm):
    class Meta:
        model = ServiceCategory
        fields = ["code", "name", "description", "is_active"]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 4}),
        }
        help_texts = {
            "code": "Để trống nếu muốn hệ thống tự sinh mã.",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.apply_common_attrs()


class ServiceForm(FormControlMixin, forms.ModelForm):
    class Meta:
        model = Service
        fields = ["code", "category", "name", "description", "duration_minutes", "is_active"]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 4}),
        }
        help_texts = {
            "code": "Để trống nếu muốn hệ thống tự sinh mã.",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.apply_common_attrs()
        self.fields["category"].queryset = ServiceCategory.objects.filter(is_active=True).order_by("name")


class PriceListForm(FormControlMixin, forms.ModelForm):
    class Meta:
        model = PriceList
        fields = ["name", "effective_from", "effective_to", "is_active", "note"]
        widgets = {
            "effective_from": forms.DateInput(attrs={"type": "date"}),
            "effective_to": forms.DateInput(attrs={"type": "date"}),
            "note": forms.Textarea(attrs={"rows": 4}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.apply_common_attrs()


class ServicePriceForm(FormControlMixin, forms.ModelForm):
    class Meta:
        model = ServicePrice
        fields = ["price_list", "service", "price", "note"]
        widgets = {
            "price": forms.NumberInput(attrs={"min": 0, "step": 1000}),
        }

    def __init__(self, *args, **kwargs):
        price_list = kwargs.pop("price_list", None)
        super().__init__(*args, **kwargs)
        if price_list:
            self.fields["price_list"].initial = price_list
            self.fields["price_list"].required = False
            self.fields["price_list"].widget = forms.HiddenInput()
        service_queryset = Service.objects.filter(is_active=True).order_by("category__name", "name")
        if price_list and not self.instance.pk:
            service_queryset = service_queryset.exclude(prices__price_list=price_list)
        elif self.instance.pk:
            service_queryset = Service.objects.filter(pk=self.instance.service_id) | service_queryset
        self.fields["service"].queryset = service_queryset.distinct().order_by("category__name", "name")
        self.apply_common_attrs()


class InvoiceForm(FormControlMixin, forms.ModelForm):
    class Meta:
        model = Invoice
        fields = [
            "invoice_code",
            "patient",
            "appointment",
            "issue_date",
            "due_date",
            "payment_type",
            "note",
        ]
        widgets = {
            "issue_date": forms.DateInput(attrs={"type": "date"}),
            "due_date": forms.DateInput(attrs={"type": "date"}),
            "note": forms.Textarea(attrs={"rows": 3}),
        }
        help_texts = {
            "invoice_code": "Để trống nếu muốn hệ thống tự sinh mã.",
            "appointment": "Có thể chọn lịch khám để liên kết hóa đơn với lần điều trị.",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["patient"].queryset = Patient.objects.filter(is_active=True).order_by("full_name")
        self.fields["appointment"].queryset = Appointment.objects.select_related(
            "patient",
            "doctor_schedule__doctor",
        ).order_by("-doctor_schedule__work_date", "-start_time")
        self.apply_common_attrs()


class InvoiceItemForm(FormControlMixin, forms.ModelForm):
    class Meta:
        model = InvoiceItem
        fields = ["invoice", "service", "description", "quantity", "unit_price", "note"]
        widgets = {
            "quantity": forms.NumberInput(attrs={"min": 1}),
            "unit_price": forms.NumberInput(attrs={"min": 0, "step": 1000}),
        }
        help_texts = {
            "description": "Để trống nếu muốn dùng tên dịch vụ đã chọn.",
        }

    def __init__(self, *args, **kwargs):
        invoice = kwargs.pop("invoice", None)
        super().__init__(*args, **kwargs)
        if invoice:
            self.fields["invoice"].initial = invoice
            self.fields["invoice"].required = False
            self.fields["invoice"].widget = forms.HiddenInput()

        service_queryset = Service.objects.filter(is_active=True).order_by("category__name", "name")
        if self.instance.pk and self.instance.service_id:
            service_queryset = Service.objects.filter(pk=self.instance.service_id) | service_queryset
        self.fields["service"].queryset = service_queryset.distinct().order_by("category__name", "name")
        self.apply_common_attrs()


class PaymentForm(FormControlMixin, forms.ModelForm):
    class Meta:
        model = Payment
        fields = ["invoice", "paid_at", "amount", "method", "note"]
        widgets = {
            "paid_at": forms.DateInput(attrs={"type": "date"}),
            "amount": forms.NumberInput(attrs={"min": 1, "step": 1, "inputmode": "numeric"}),
        }
        help_texts = {
            "amount": "Nhập số tiền bệnh nhân trả trong lần này, chỉ nhập số. Ví dụ: 500000.",
        }

    def __init__(self, *args, **kwargs):
        invoice = kwargs.pop("invoice", None)
        self.invoice = invoice
        super().__init__(*args, **kwargs)
        if invoice:
            self.fields["invoice"].initial = invoice
            self.fields["invoice"].required = False
            self.fields["invoice"].widget = forms.HiddenInput()
            if not self.instance.pk:
                self.fields["amount"].initial = invoice.outstanding_amount
        self.apply_common_attrs()

    def clean_amount(self):
        amount = self.cleaned_data["amount"]
        invoice = self.invoice or self.cleaned_data.get("invoice")
        if invoice and amount:
            paid_before = invoice.payments.exclude(pk=self.instance.pk).aggregate(total=Sum("amount"))["total"] or 0
            if invoice.total_amount and paid_before + amount > invoice.total_amount:
                raise forms.ValidationError("Số tiền thanh toán vượt quá số tiền còn lại của hóa đơn.")
        return amount


class MoMoPaymentForm(FormControlMixin, forms.ModelForm):
    class Meta:
        model = PaymentTransaction
        fields = ["amount", "customer_email"]
        widgets = {
            "amount": forms.NumberInput(attrs={"min": 1000, "step": 1000, "inputmode": "numeric"}),
        }
        help_texts = {
            "amount": "MoMo yêu cầu tối thiểu 1.000 VND cho một giao dịch.",
            "customer_email": "Biên nhận thanh toán sẽ được gửi tới email này sau khi MoMo xác nhận thành công.",
        }

    def __init__(self, *args, **kwargs):
        self.invoice = kwargs.pop("invoice")
        super().__init__(*args, **kwargs)
        if not self.instance.pk:
            self.fields["amount"].initial = self.invoice.outstanding_amount
            self.fields["customer_email"].initial = self.invoice.patient.email
        self.apply_common_attrs()

    def clean_amount(self):
        amount = self.cleaned_data["amount"]
        if amount < 1000:
            raise forms.ValidationError("MoMo chỉ hỗ trợ giao dịch từ 1.000 VND trở lên.")
        if amount > 50000000:
            raise forms.ValidationError("MoMo chỉ hỗ trợ tối đa 50.000.000 VND cho một giao dịch.")
        if amount > self.invoice.outstanding_amount:
            raise forms.ValidationError("Số tiền thanh toán không được vượt quá số tiền còn nợ của hóa đơn.")
        return amount


class MedicineForm(FormControlMixin, forms.ModelForm):
    class Meta:
        model = Medicine
        fields = [
            "medicine_code",
            "name",
            "active_ingredient",
            "strength",
            "unit",
            "usage_note",
            "is_active",
        ]
        widgets = {
            "usage_note": forms.Textarea(attrs={"rows": 3}),
        }
        help_texts = {
            "medicine_code": "Để trống nếu muốn hệ thống tự sinh mã.",
            "strength": "Ví dụ: 500mg, 250mg/5ml.",
            "unit": "Ví dụ: viên, gói, chai, tuýp.",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.apply_common_attrs()


class SupplyForm(FormControlMixin, forms.ModelForm):
    class Meta:
        model = Supply
        fields = [
            "supply_code",
            "name",
            "category",
            "unit",
            "minimum_quantity",
            "description",
            "is_active",
        ]
        widgets = {
            "minimum_quantity": forms.NumberInput(attrs={"min": 0, "step": "0.01"}),
            "description": forms.Textarea(attrs={"rows": 3}),
        }
        help_texts = {
            "supply_code": "Để trống nếu muốn hệ thống tự sinh mã.",
            "minimum_quantity": "Hệ thống cảnh báo khi tồn kho nhỏ hơn hoặc bằng ngưỡng này.",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.apply_common_attrs()


class SupplyLotForm(FormControlMixin, forms.ModelForm):
    class Meta:
        model = SupplyLot
        fields = [
            "supply",
            "lot_number",
            "supplier",
            "received_date",
            "expiry_date",
            "initial_quantity",
            "unit_cost",
            "note",
        ]
        widgets = {
            "received_date": forms.DateInput(attrs={"type": "date"}),
            "expiry_date": forms.DateInput(attrs={"type": "date"}),
            "initial_quantity": forms.NumberInput(attrs={"min": "0.01", "step": "0.01"}),
            "unit_cost": forms.NumberInput(attrs={"min": 0, "step": 1000}),
            "note": forms.Textarea(attrs={"rows": 3}),
        }
        help_texts = {
            "lot_number": "Ví dụ: LOT-2026-05 hoặc số lô trên bao bì.",
            "expiry_date": "Để trống nếu vật tư không có hạn sử dụng.",
        }

    def __init__(self, *args, **kwargs):
        supply = kwargs.pop("supply", None)
        super().__init__(*args, **kwargs)
        if supply:
            self.fields["supply"].initial = supply
            self.fields["supply"].required = False
            self.fields["supply"].widget = forms.HiddenInput()
        supply_queryset = Supply.objects.filter(is_active=True).order_by("category", "name")
        if self.instance.pk and self.instance.supply_id:
            supply_queryset = Supply.objects.filter(pk=self.instance.supply_id) | supply_queryset
        self.fields["supply"].queryset = supply_queryset.distinct().order_by("category", "name")
        self.apply_common_attrs()


class SupplyExportForm(FormControlMixin, forms.ModelForm):
    class Meta:
        model = SupplyExport
        fields = ["lot", "export_date", "quantity", "used_for", "performed_by", "note"]
        widgets = {
            "export_date": forms.DateInput(attrs={"type": "date"}),
            "quantity": forms.NumberInput(attrs={"min": "0.01", "step": "0.01"}),
            "note": forms.Textarea(attrs={"rows": 3}),
        }
        help_texts = {
            "lot": "Chỉ hiển thị các lô còn tồn và chưa hết hạn.",
        }

    def __init__(self, *args, **kwargs):
        supply = kwargs.pop("supply", None)
        super().__init__(*args, **kwargs)
        today = timezone.localdate()
        lot_queryset = SupplyLot.objects.select_related("supply").filter(current_quantity__gt=0).filter(
            Q(expiry_date__isnull=True) | Q(expiry_date__gte=today)
        )
        if supply:
            lot_queryset = lot_queryset.filter(supply=supply)
        if self.instance.pk and self.instance.lot_id:
            lot_queryset = SupplyLot.objects.filter(pk=self.instance.lot_id) | lot_queryset
        self.fields["lot"].queryset = lot_queryset.distinct().order_by("expiry_date", "received_date", "id")
        self.fields["performed_by"].queryset = Staff.objects.filter(is_active=True).order_by("full_name")
        self.apply_common_attrs()


class PrescriptionForm(FormControlMixin, forms.ModelForm):
    class Meta:
        model = Prescription
        fields = [
            "prescription_code",
            "patient",
            "appointment",
            "doctor",
            "prescribed_at",
            "diagnosis",
            "note",
        ]
        widgets = {
            "prescribed_at": forms.DateInput(attrs={"type": "date"}),
            "note": forms.Textarea(attrs={"rows": 3}),
        }
        help_texts = {
            "prescription_code": "Để trống nếu muốn hệ thống tự sinh mã.",
            "appointment": "Chọn lịch khám nếu kê đơn sau khi khám.",
        }

    def __init__(self, *args, **kwargs):
        staff_user = kwargs.pop("staff_user", None)
        super().__init__(*args, **kwargs)
        doctor = get_doctor_profile(staff_user)

        patient_queryset = Patient.objects.filter(is_active=True).order_by("full_name")
        appointment_queryset = Appointment.objects.select_related(
            "patient",
            "doctor_schedule__doctor",
        )
        doctor_queryset = Staff.objects.filter(
            role=Staff.Role.DOCTOR,
            is_active=True,
        )

        if doctor:
            appointment_queryset = appointment_queryset.filter(doctor_schedule__doctor=doctor)
            patient_queryset = patient_queryset.filter(appointments__doctor_schedule__doctor=doctor).distinct()
            doctor_queryset = doctor_queryset.filter(pk=doctor.pk)
            self.fields["doctor"].initial = doctor
            self.fields["doctor"].widget = forms.HiddenInput()

        self.fields["patient"].queryset = patient_queryset.order_by("full_name")
        self.fields["appointment"].queryset = appointment_queryset.order_by(
            "-doctor_schedule__work_date",
            "-start_time",
        )
        self.fields["doctor"].queryset = doctor_queryset.order_by("full_name")
        self.apply_common_attrs()


class PrescriptionItemForm(FormControlMixin, forms.ModelForm):
    class Meta:
        model = PrescriptionItem
        fields = ["prescription", "medicine", "dosage", "quantity", "instructions", "note"]
        widgets = {
            "quantity": forms.NumberInput(attrs={"min": 1}),
            "instructions": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        prescription = kwargs.pop("prescription", None)
        super().__init__(*args, **kwargs)
        if prescription:
            self.fields["prescription"].initial = prescription
            self.fields["prescription"].required = False
            self.fields["prescription"].widget = forms.HiddenInput()

        medicine_queryset = Medicine.objects.filter(is_active=True).order_by("name", "strength")
        if self.instance.pk:
            medicine_queryset = Medicine.objects.filter(pk=self.instance.medicine_id) | medicine_queryset
        self.fields["medicine"].queryset = medicine_queryset.distinct().order_by("name", "strength")
        self.apply_common_attrs()


class ClinicHolidayForm(FormControlMixin, forms.ModelForm):
    class Meta:
        model = ClinicHoliday
        fields = ["date", "name", "note", "is_active"]
        widgets = {
            "date": forms.DateInput(attrs={"type": "date"}),
            "note": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.apply_common_attrs()


class WorkShiftForm(FormControlMixin, forms.ModelForm):
    class Meta:
        model = WorkShift
        fields = ["name", "weekday", "start_time", "end_time", "shift_coefficient", "is_active", "note"]
        widgets = {
            "start_time": forms.TimeInput(attrs={"type": "time"}),
            "end_time": forms.TimeInput(attrs={"type": "time"}),
            "shift_coefficient": forms.NumberInput(attrs={"min": "1.00", "max": "2.00", "step": "0.01"}),
            "note": forms.Textarea(attrs={"rows": 3}),
        }
        help_texts = {
            "shift_coefficient": "Hành chính: 1.0. Ngoài giờ / cuối tuần: 1.1–1.5.",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.apply_common_attrs()

    def clean_shift_coefficient(self):
        val = self.cleaned_data.get("shift_coefficient")
        if val is None:
            from decimal import Decimal
            return Decimal("1.00")
        return val


class DoctorScheduleForm(FormControlMixin, forms.ModelForm):
    shifts = forms.ModelMultipleChoiceField(
        queryset=WorkShift.objects.none(),
        widget=forms.CheckboxSelectMultiple,
        label="Ca làm việc",
        required=True,
    )

    class Meta:
        model = DoctorSchedule
        fields = ["doctor", "work_date", "status", "note"]
        widgets = {
            "work_date": forms.DateInput(attrs={"type": "date"}),
            "note": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        # Handle backwards compatibility for single 'shift' in POST data
        data = kwargs.get("data")
        if data:
            if "shift" in data and "shifts" not in data:
                if hasattr(data, "copy"):
                    mutable_data = data.copy()
                    if hasattr(mutable_data, "setlist"):
                        mutable_data.setlist("shifts", mutable_data.getlist("shift"))
                    else:
                        mutable_data["shifts"] = [mutable_data["shift"]]
                    kwargs["data"] = mutable_data
                else:
                    data = dict(data)
                    data["shifts"] = [data["shift"]]
                    kwargs["data"] = data

        super().__init__(*args, **kwargs)
        self.fields["doctor"].queryset = Staff.objects.filter(
            role=Staff.Role.DOCTOR,
            is_active=True,
        ).order_by("full_name")
        
        shifts_qs = WorkShift.objects.filter(is_active=True).order_by(
            "weekday",
            "start_time",
            "name",
        )
        self.fields["shifts"].queryset = shifts_qs
        
        if self.instance.pk and self.instance.shift_id:
            self.fields["shifts"].initial = [self.instance.shift_id]
            
        self.apply_common_attrs()

    def clean(self):
        cleaned_data = super().clean()
        doctor = cleaned_data.get("doctor")
        work_date = cleaned_data.get("work_date")
        shifts = cleaned_data.get("shifts")

        if doctor and work_date and shifts:
            weekday = work_date.weekday()
            for shift in shifts:
                if shift.weekday != weekday:
                    self.add_error(
                        "shifts",
                        f"Ca '{shift.name}' không thuộc ngày {work_date.strftime('%d/%m/%Y')} (Thứ {weekday + 2 if weekday < 6 else 'Chủ nhật'})."
                    )

                existing_query = DoctorSchedule.objects.filter(
                    doctor=doctor,
                    work_date=work_date,
                    shift=shift,
                )
                if self.instance.pk:
                    existing_query = existing_query.exclude(pk=self.instance.pk)

                if existing_query.exists():
                    self.add_error(
                        "shifts",
                        f"Bác sĩ đã có lịch đăng ký cho ca '{shift.name}' vào ngày {work_date.strftime('%d/%m/%Y')}."
                    )
        return cleaned_data

    @transaction.atomic
    def save(self, commit=True):
        selected_shifts = self.cleaned_data.get("shifts")
        
        if self.instance.pk:
            if selected_shifts:
                self.instance.shift = selected_shifts[0]
            schedule = super().save(commit=commit)
            return schedule

        created_schedules = []
        for idx, shift in enumerate(selected_shifts):
            if idx == 0:
                self.instance.shift = shift
                schedule = super().save(commit=commit)
                created_schedules.append(schedule)
            else:
                schedule = DoctorSchedule(
                    doctor=self.cleaned_data["doctor"],
                    work_date=self.cleaned_data["work_date"],
                    shift=shift,
                    status=self.cleaned_data["status"],
                    note=self.cleaned_data.get("note", ""),
                )
                if commit:
                    schedule.save()
                created_schedules.append(schedule)
        return created_schedules[0] if created_schedules else self.instance


class AppointmentForm(FormControlMixin, forms.ModelForm):
    class Meta:
        model = Appointment
        fields = [
            "appointment_code",
            "patient",
            "doctor_schedule",
            "service",
            "start_time",
            "end_time",
            "arrival_type",
            "visit_type",
            "priority_level",
            "status",
            "chief_complaint",
            "note",
        ]
        widgets = {
            "start_time": forms.TimeInput(attrs={"type": "time"}),
            "end_time": forms.TimeInput(attrs={"type": "time"}),
            "note": forms.Textarea(attrs={"rows": 3}),
        }
        help_texts = {
            "appointment_code": "Để trống nếu muốn hệ thống tự sinh mã.",
            "doctor_schedule": "Chọn lịch trực đã đăng ký của bác sĩ.",
        }

    def __init__(self, *args, **kwargs):
        staff_user = kwargs.pop("staff_user", None)
        super().__init__(*args, **kwargs)
        doctor = get_doctor_profile(staff_user)
        self.fields["patient"].queryset = Patient.objects.filter(is_active=True).order_by("full_name")
        schedule_queryset = DoctorSchedule.objects.select_related("doctor", "shift").filter(
            status=DoctorSchedule.Status.REGISTERED,
            shift__is_active=True,
        )
        if doctor:
            schedule_queryset = schedule_queryset.filter(doctor=doctor)
        self.fields["doctor_schedule"].queryset = schedule_queryset.order_by(
            "-work_date",
            "shift__start_time",
            "doctor__full_name",
        )
        self.fields["service"].queryset = Service.objects.filter(is_active=True).order_by("category__name", "name")
        self.apply_common_attrs()


class DoctorAppointmentForm(FormControlMixin, forms.ModelForm):
    class Meta:
        model = Appointment
        fields = [
            "visit_type",
            "priority_level",
            "status",
            "chief_complaint",
            "note",
        ]
        widgets = {
            "note": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        kwargs.pop("staff_user", None)
        super().__init__(*args, **kwargs)
        self.apply_common_attrs()


class ReceptionWalkInForm(FormControlMixin, forms.Form):
    patient = forms.ModelChoiceField(
        label="Bệnh nhân hiện có",
        queryset=Patient.objects.none(),
        required=False,
        help_text="Chọn bệnh nhân cũ nếu đã có hồ sơ. Nếu để trống, hệ thống sẽ tạo hồ sơ nhanh bên dưới.",
    )
    new_full_name = forms.CharField(label="Họ và tên bệnh nhân mới", max_length=150, required=False)
    new_phone = forms.CharField(label="Số điện thoại", max_length=30, required=False)
    new_gender = forms.ChoiceField(label="Giới tính", choices=Patient.Gender.choices, required=False)
    new_date_of_birth = forms.DateField(
        label="Ngày sinh",
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    doctor_schedule = forms.ModelChoiceField(
        label="Bác sĩ / ca trực hôm nay",
        queryset=DoctorSchedule.objects.none(),
        help_text="Chỉ hiển thị các lịch trực còn hiệu lực trong ngày hôm nay.",
    )
    service = forms.ModelChoiceField(
        label="Dịch vụ dự kiến",
        queryset=Service.objects.none(),
        required=False,
    )
    visit_type = forms.ChoiceField(
        label="Phân loại lượt khám",
        choices=Appointment.VisitType.choices,
        initial=Appointment.VisitType.NEW,
    )
    priority_level = forms.ChoiceField(
        label="Mức độ ưu tiên",
        choices=Appointment.PriorityLevel.choices,
        initial=Appointment.PriorityLevel.NORMAL,
    )
    chief_complaint = forms.CharField(label="Lý do khám", max_length=255)
    note = forms.CharField(
        label="Ghi chú tiếp đón",
        required=False,
        widget=forms.Textarea(attrs={"rows": 3}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        today = timezone.localdate()
        self.fields["patient"].queryset = Patient.objects.filter(is_active=True).order_by("full_name")
        self.fields["doctor_schedule"].queryset = DoctorSchedule.objects.select_related("doctor", "shift").filter(
            work_date=today,
            status=DoctorSchedule.Status.REGISTERED,
            doctor__is_active=True,
            shift__is_active=True,
        ).order_by("shift__start_time", "doctor__full_name")
        self.fields["service"].queryset = Service.objects.filter(is_active=True).order_by("category__name", "name")
        self.fields["doctor_schedule"].label_from_instance = (
            lambda schedule: (
                f"{schedule.doctor.full_name} - {schedule.shift.name} "
                f"({schedule.shift.start_time:%H:%M} - {schedule.shift.end_time:%H:%M})"
            )
        )
        self.apply_common_attrs()

    def clean(self):
        cleaned_data = super().clean()
        patient = cleaned_data.get("patient")
        new_full_name = (cleaned_data.get("new_full_name") or "").strip()

        if not patient and not new_full_name:
            raise forms.ValidationError("Chọn bệnh nhân hiện có hoặc nhập họ tên để tạo hồ sơ nhanh.")

        return cleaned_data

    @transaction.atomic
    def save_patient(self):
        patient = self.cleaned_data.get("patient")
        if patient:
            return patient

        return Patient.objects.create(
            full_name=self.cleaned_data["new_full_name"].strip(),
            phone=(self.cleaned_data.get("new_phone") or "").strip(),
            gender=self.cleaned_data.get("new_gender") or Patient.Gender.MALE,
            date_of_birth=self.cleaned_data.get("new_date_of_birth"),
        )
