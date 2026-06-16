from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models, transaction
from django.db.models import Max, Sum
from django.conf import settings
from django.utils import timezone


class TimestampedModel(models.Model):
    created_at = models.DateTimeField("Ngày tạo", auto_now_add=True)
    updated_at = models.DateTimeField("Ngày cập nhật", auto_now=True)

    class Meta:
        abstract = True


class Patient(TimestampedModel):
    class Gender(models.TextChoices):
        MALE = "male", "Nam"
        FEMALE = "female", "Nữ"
        OTHER = "other", "Khác"

    class BloodType(models.TextChoices):
        UNKNOWN = "", "Chưa rõ"
        A_POSITIVE = "A+", "A+"
        A_NEGATIVE = "A-", "A-"
        B_POSITIVE = "B+", "B+"
        B_NEGATIVE = "B-", "B-"
        AB_POSITIVE = "AB+", "AB+"
        AB_NEGATIVE = "AB-", "AB-"
        O_POSITIVE = "O+", "O+"
        O_NEGATIVE = "O-", "O-"

    patient_code = models.CharField("Mã bệnh nhân", max_length=30, unique=True, blank=True)
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        verbose_name="Tài khoản đăng nhập",
        blank=True,
        null=True,
        on_delete=models.SET_NULL,
        related_name="patient_profile",
    )
    full_name = models.CharField("Họ và tên", max_length=150)
    date_of_birth = models.DateField("Ngày sinh", blank=True, null=True)
    gender = models.CharField("Giới tính", max_length=10, choices=Gender.choices, default=Gender.MALE)
    national_id = models.CharField("CCCD / CMND", max_length=30, blank=True)
    phone = models.CharField("Số điện thoại", max_length=30, blank=True)
    email = models.EmailField("Email", blank=True)
    address = models.CharField("Địa chỉ", max_length=255, blank=True)
    occupation = models.CharField("Nghề nghiệp", max_length=150, blank=True)
    emergency_contact_name = models.CharField("Người liên hệ khẩn cấp", max_length=150, blank=True)
    emergency_contact_phone = models.CharField("SĐT khẩn cấp", max_length=30, blank=True)
    blood_type = models.CharField("Nhóm máu", max_length=3, choices=BloodType.choices, blank=True)
    medical_history = models.TextField("Tiền sử bệnh", blank=True)
    current_medications = models.TextField("Thuốc đang sử dụng", blank=True)
    allergy_note = models.TextField("Dị ứng / ghi chú y tế", blank=True)
    note = models.TextField("Ghi chú khác", blank=True)
    is_active = models.BooleanField("Đang hoạt động", default=True)

    class Meta:
        ordering = ["full_name"]
        verbose_name = "Bệnh nhân"
        verbose_name_plural = "Bệnh nhân"

    def __str__(self):
        return f"{self.patient_code} - {self.full_name}" if self.patient_code else self.full_name

    def save(self, *args, **kwargs):
        if not self.patient_code:
            self.patient_code = self._generate_patient_code()
        super().save(*args, **kwargs)

    def _generate_patient_code(self):
        max_id = Patient.objects.aggregate(value=Max("id"))["value"] or 0
        next_number = max_id + 1
        while True:
            candidate = f"BN-{next_number:05d}"
            if not Patient.objects.filter(patient_code=candidate).exists():
                return candidate
            next_number += 1

    @property
    def age(self):
        if not self.date_of_birth:
            return None
        today = timezone.localdate()
        return today.year - self.date_of_birth.year - (
            (today.month, today.day) < (self.date_of_birth.month, self.date_of_birth.day)
        )


class Staff(TimestampedModel):
    class Gender(models.TextChoices):
        MALE = "male", "Nam"
        FEMALE = "female", "Nữ"
        OTHER = "other", "Khác"

    class Role(models.TextChoices):
        DOCTOR = "doctor", "Bác sĩ"
        ASSISTANT = "assistant", "Trợ thủ nha khoa"
        RECEPTIONIST = "receptionist", "Lễ tân"
        TECHNICIAN = "technician", "Kỹ thuật viên"
        MANAGER = "manager", "Quản lý"
        OTHER = "other", "Khác"

    employee_code = models.CharField("Mã số", max_length=30, unique=True, blank=True)
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        verbose_name="Tài khoản đăng nhập",
        blank=True,
        null=True,
        on_delete=models.SET_NULL,
        related_name="staff_profile",
    )
    role = models.CharField("Chức danh", max_length=30, choices=Role.choices, default=Role.DOCTOR)
    full_name = models.CharField("Họ tên", max_length=150)
    date_of_birth = models.DateField("Ngày sinh", blank=True, null=True)
    gender = models.CharField("Giới tính", max_length=10, choices=Gender.choices, blank=True)
    phone = models.CharField("Điện thoại", max_length=30, blank=True)
    email = models.EmailField("Email", blank=True)
    address = models.CharField("Địa chỉ", max_length=255, blank=True)
    primary_workplace = models.CharField("Nơi công tác chính thức", max_length=255, blank=True)
    degree = models.CharField("Bằng cấp / học hàm học vị", max_length=255, blank=True)
    specialization = models.CharField("Chuyên môn", max_length=255, blank=True)
    license_number = models.CharField("Số chứng chỉ hành nghề", max_length=80, blank=True)
    experience_years = models.PositiveSmallIntegerField(
        "Số năm kinh nghiệm",
        blank=True,
        null=True,
        validators=[MaxValueValidator(80)],
    )
    start_date = models.DateField("Ngày bắt đầu làm việc", blank=True, null=True)
    salary_coefficient = models.DecimalField(
        "Hệ số bác sĩ",
        max_digits=4,
        decimal_places=2,
        default=Decimal("1.30"),
        validators=[MinValueValidator(Decimal("0.50")), MaxValueValidator(Decimal("5.00"))],
        blank=True,
        help_text="Theo học hàm học vị: Đại học=1.3, Thạc sĩ=1.5, Tiến sĩ=1.7, PGS=2.0, GS=2.5",
    )
    emergency_contact_name = models.CharField("Người liên hệ khẩn cấp", max_length=150, blank=True)
    emergency_contact_phone = models.CharField("SĐT khẩn cấp", max_length=30, blank=True)
    note = models.TextField("Ghi chú", blank=True)
    is_active = models.BooleanField("Đang làm việc", default=True)

    class Meta:
        ordering = ["full_name"]
        verbose_name = "Nhân viên / bác sĩ"
        verbose_name_plural = "Nhân viên / bác sĩ"

    def __str__(self):
        return f"{self.employee_code} - {self.full_name}" if self.employee_code else self.full_name

    def save(self, *args, **kwargs):
        if not self.employee_code:
            self.employee_code = self._generate_employee_code()
        super().save(*args, **kwargs)

    def _generate_employee_code(self):
        prefix = "BS" if self.role == self.Role.DOCTOR else "NV"
        max_id = Staff.objects.aggregate(value=Max("id"))["value"] or 0
        next_number = max_id + 1

        while True:
            candidate = f"{prefix}-{next_number:05d}"
            if not Staff.objects.filter(employee_code=candidate).exists():
                return candidate
            next_number += 1


class ServiceCategory(TimestampedModel):
    code = models.CharField("Mã danh mục", max_length=30, unique=True, blank=True)
    name = models.CharField("Tên danh mục", max_length=150, unique=True)
    description = models.TextField("Mô tả", blank=True)
    is_active = models.BooleanField("Đang sử dụng", default=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "Danh mục dịch vụ"
        verbose_name_plural = "Danh mục dịch vụ"

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.code:
            self.code = self._generate_category_code()
        super().save(*args, **kwargs)

    @staticmethod
    def _generate_category_code():
        max_id = ServiceCategory.objects.aggregate(value=Max("id"))["value"] or 0
        next_number = max_id + 1

        while True:
            candidate = f"DM-{next_number:04d}"
            if not ServiceCategory.objects.filter(code=candidate).exists():
                return candidate
            next_number += 1


class Service(TimestampedModel):
    code = models.CharField("Mã dịch vụ", max_length=30, unique=True, blank=True)
    category = models.ForeignKey(
        ServiceCategory,
        verbose_name="Danh mục",
        on_delete=models.PROTECT,
        related_name="services",
    )
    name = models.CharField("Tên dịch vụ", max_length=200)
    description = models.TextField("Mô tả", blank=True)
    duration_minutes = models.PositiveIntegerField("Thời lượng dự kiến (phút)", blank=True, null=True)
    is_active = models.BooleanField("Đang sử dụng", default=True)

    class Meta:
        ordering = ["category__name", "name"]
        unique_together = [("category", "name")]
        verbose_name = "Dịch vụ"
        verbose_name_plural = "Dịch vụ"

    def __str__(self):
        return f"{self.code} - {self.name}" if self.code else self.name

    def save(self, *args, **kwargs):
        if not self.code:
            self.code = self._generate_service_code()
        super().save(*args, **kwargs)

    @staticmethod
    def _generate_service_code():
        max_id = Service.objects.aggregate(value=Max("id"))["value"] or 0
        next_number = max_id + 1

        while True:
            candidate = f"DV-{next_number:05d}"
            if not Service.objects.filter(code=candidate).exists():
                return candidate
            next_number += 1


class PriceList(TimestampedModel):
    name = models.CharField("Tên bảng giá", max_length=150)
    effective_from = models.DateField("Áp dụng từ")
    effective_to = models.DateField("Áp dụng đến", blank=True, null=True)
    is_active = models.BooleanField("Đang áp dụng", default=True)
    note = models.TextField("Ghi chú", blank=True)

    class Meta:
        ordering = ["-effective_from", "name"]
        verbose_name = "Bảng giá dịch vụ"
        verbose_name_plural = "Bảng giá dịch vụ"

    def __str__(self):
        return self.name

    def clean(self):
        super().clean()
        if self.effective_to and self.effective_to < self.effective_from:
            raise ValidationError({"effective_to": "Ngày kết thúc không được trước ngày bắt đầu."})


class ServicePrice(TimestampedModel):
    price_list = models.ForeignKey(
        PriceList,
        verbose_name="Bảng giá",
        on_delete=models.CASCADE,
        related_name="prices",
    )
    service = models.ForeignKey(
        Service,
        verbose_name="Dịch vụ",
        on_delete=models.PROTECT,
        related_name="prices",
    )
    price = models.DecimalField(
        "Đơn giá",
        max_digits=12,
        decimal_places=0,
        validators=[MinValueValidator(Decimal("0"))],
    )
    note = models.CharField("Ghi chú", max_length=255, blank=True)

    class Meta:
        ordering = ["service__category__name", "service__name"]
        unique_together = [("price_list", "service")]
        verbose_name = "Giá dịch vụ"
        verbose_name_plural = "Giá dịch vụ"

    def __str__(self):
        return f"{self.service} - {self.price:,.0f}"


class ClinicHoliday(TimestampedModel):
    date = models.DateField("Ngày nghỉ", unique=True)
    name = models.CharField("Tên ngày nghỉ", max_length=150)
    note = models.TextField("Ghi chú", blank=True)
    is_active = models.BooleanField("Đang áp dụng", default=True)

    class Meta:
        ordering = ["-date"]
        verbose_name = "Ngày nghỉ"
        verbose_name_plural = "Ngày nghỉ"

    def __str__(self):
        return f"{self.date:%d/%m/%Y} - {self.name}"


class WorkShift(TimestampedModel):
    class Weekday(models.IntegerChoices):
        MONDAY = 0, "Thứ hai"
        TUESDAY = 1, "Thứ ba"
        WEDNESDAY = 2, "Thứ tư"
        THURSDAY = 3, "Thứ năm"
        FRIDAY = 4, "Thứ sáu"
        SATURDAY = 5, "Thứ bảy"
        SUNDAY = 6, "Chủ nhật"

    name = models.CharField("Tên ca", max_length=120)
    weekday = models.PositiveSmallIntegerField("Ngày làm việc", choices=Weekday.choices)
    start_time = models.TimeField("Giờ bắt đầu")
    end_time = models.TimeField("Giờ kết thúc")
    shift_coefficient = models.DecimalField(
        "Hệ số ca",
        max_digits=4,
        decimal_places=2,
        default=Decimal("1.00"),
        validators=[MinValueValidator(Decimal("1.00")), MaxValueValidator(Decimal("2.00"))],
        blank=True,
        help_text="Trong giờ hành chính: 1.0. Ngoài giờ / cuối tuần: 1.1–1.5",
    )
    is_active = models.BooleanField("Đang sử dụng", default=True)
    note = models.TextField("Ghi chú", blank=True)

    class Meta:
        ordering = ["weekday", "start_time", "name"]
        unique_together = [("weekday", "name")]
        verbose_name = "Ca làm việc"
        verbose_name_plural = "Ca làm việc"

    def __str__(self):
        start = self.start_time.strftime("%H:%M") if self.start_time else "--:--"
        end = self.end_time.strftime("%H:%M") if self.end_time else "--:--"
        return f"{self.name} - {self.get_weekday_display()} ({start}-{end})"

    def clean(self):
        super().clean()
        errors = {}

        if self.start_time and self.end_time and self.end_time <= self.start_time:
            errors["end_time"] = "Giờ kết thúc phải sau giờ bắt đầu."

        if self.is_active and self.weekday is not None and self.start_time and self.end_time:
            overlapping_shift = (
                WorkShift.objects.filter(
                    weekday=self.weekday,
                    is_active=True,
                    start_time__lt=self.end_time,
                    end_time__gt=self.start_time,
                )
                .exclude(pk=self.pk)
                .exists()
            )
            if overlapping_shift:
                errors["start_time"] = "Ca làm việc đang trùng thời gian với ca khác trong cùng ngày."

        if errors:
            raise ValidationError(errors)


class DoctorSchedule(TimestampedModel):
    class Status(models.TextChoices):
        REGISTERED = "registered", "Đã đăng ký"
        CANCELLED = "cancelled", "Đã hủy"
        COMPLETED = "completed", "Đã hoàn tất"

    doctor = models.ForeignKey(
        Staff,
        verbose_name="Bác sĩ",
        on_delete=models.PROTECT,
        related_name="doctor_schedules",
    )
    work_date = models.DateField("Ngày trực")
    shift = models.ForeignKey(
        WorkShift,
        verbose_name="Ca làm việc",
        on_delete=models.PROTECT,
        related_name="doctor_schedules",
    )
    status = models.CharField(
        "Trạng thái",
        max_length=20,
        choices=Status.choices,
        default=Status.REGISTERED,
    )
    note = models.TextField("Ghi chú", blank=True)

    class Meta:
        ordering = ["-work_date", "shift__start_time", "doctor__full_name"]
        unique_together = [("doctor", "work_date", "shift")]
        verbose_name = "Lịch trực bác sĩ"
        verbose_name_plural = "Lịch trực bác sĩ"

    def __str__(self):
        return f"{self.doctor} - {self.work_date:%d/%m/%Y} - {self.shift.name}"

    def clean(self):
        super().clean()
        errors = {}

        if self.doctor_id:
            if self.doctor.role != Staff.Role.DOCTOR:
                errors["doctor"] = "Chỉ nhân sự có chức danh bác sĩ mới được đăng ký lịch trực."
            elif not self.doctor.is_active:
                errors["doctor"] = "Bác sĩ này đang ngưng làm việc."

        if self.shift_id and not self.shift.is_active and self.status != self.Status.CANCELLED:
            errors["shift"] = "Ca làm việc này đang ngưng sử dụng."

        if self.work_date and self.shift_id and self.work_date.weekday() != self.shift.weekday:
            errors["shift"] = "Ca làm việc không thuộc ngày trong tuần của ngày trực đã chọn."

        if (
            self.work_date
            and self.status != self.Status.CANCELLED
            and ClinicHoliday.objects.filter(date=self.work_date, is_active=True).exists()
        ):
            errors["work_date"] = "Ngày này đã được thiết lập là ngày nghỉ."

        if (
            self.doctor_id
            and self.work_date
            and self.shift_id
            and self.status != self.Status.CANCELLED
            and self.shift.start_time
            and self.shift.end_time
        ):
            overlapping_schedule = (
                DoctorSchedule.objects.filter(doctor=self.doctor, work_date=self.work_date)
                .exclude(status=self.Status.CANCELLED)
                .filter(
                    shift__start_time__lt=self.shift.end_time,
                    shift__end_time__gt=self.shift.start_time,
                )
                .exclude(pk=self.pk)
                .exists()
            )
            if overlapping_schedule:
                errors["shift"] = "Bác sĩ đã có lịch trực trùng thời gian."

        if errors:
            raise ValidationError(errors)


class Appointment(TimestampedModel):
    class ArrivalType(models.TextChoices):
        SCHEDULED = "scheduled", "Có lịch hẹn"
        WALK_IN = "walk_in", "Không hẹn trước"

    class VisitType(models.TextChoices):
        NEW = "new", "Khám mới"
        FOLLOW_UP = "follow_up", "Tái khám"
        TREATMENT = "treatment", "Điều trị theo liệu trình"
        EMERGENCY = "emergency", "Cấp cứu"
        WARRANTY = "warranty", "Bảo hành"

    class PriorityLevel(models.TextChoices):
        NORMAL = "normal", "Bình thường"
        PRIORITY = "priority", "Ưu tiên"
        URGENT = "urgent", "Khẩn"

    class Status(models.TextChoices):
        SCHEDULED = "scheduled", "Đã đặt"
        CONFIRMED = "confirmed", "Đã xác nhận"
        CHECKED_IN = "checked_in", "Đã đến"
        COMPLETED = "completed", "Hoàn tất"
        CANCELLED = "cancelled", "Đã hủy"
        NO_SHOW = "no_show", "Không đến"

    appointment_code = models.CharField("Mã lịch khám", max_length=30, unique=True, blank=True)
    patient = models.ForeignKey(
        Patient,
        verbose_name="Bệnh nhân",
        on_delete=models.PROTECT,
        related_name="appointments",
    )
    doctor_schedule = models.ForeignKey(
        DoctorSchedule,
        verbose_name="Lịch trực bác sĩ",
        on_delete=models.PROTECT,
        related_name="appointments",
    )
    service = models.ForeignKey(
        Service,
        verbose_name="Dịch vụ dự kiến",
        on_delete=models.PROTECT,
        related_name="appointments",
        blank=True,
        null=True,
    )
    start_time = models.TimeField("Giờ bắt đầu")
    end_time = models.TimeField("Giờ kết thúc")
    arrival_type = models.CharField(
        "Nguồn tiếp nhận",
        max_length=20,
        choices=ArrivalType.choices,
        default=ArrivalType.SCHEDULED,
    )
    visit_type = models.CharField(
        "Phân loại lượt khám",
        max_length=20,
        choices=VisitType.choices,
        default=VisitType.NEW,
    )
    priority_level = models.CharField(
        "Mức độ ưu tiên",
        max_length=20,
        choices=PriorityLevel.choices,
        default=PriorityLevel.NORMAL,
    )
    status = models.CharField(
        "Trạng thái",
        max_length=20,
        choices=Status.choices,
        default=Status.SCHEDULED,
    )
    queue_number = models.PositiveIntegerField("Số thứ tự tiếp đón", blank=True, null=True)
    checked_in_at = models.DateTimeField("Thời điểm tiếp đón", blank=True, null=True)
    checked_in_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="Lễ tân tiếp đón",
        on_delete=models.SET_NULL,
        related_name="checked_in_appointments",
        blank=True,
        null=True,
    )
    chief_complaint = models.CharField("Lý do khám", max_length=255, blank=True)
    note = models.TextField("Ghi chú", blank=True)

    class Meta:
        ordering = ["-doctor_schedule__work_date", "start_time", "patient__full_name"]
        verbose_name = "Lịch khám"
        verbose_name_plural = "Lịch khám"

    def __str__(self):
        return f"{self.appointment_code} - {self.patient} - {self.appointment_date:%d/%m/%Y}"

    def save(self, *args, **kwargs):
        if not self.appointment_code:
            self.appointment_code = self._generate_appointment_code()
        super().save(*args, **kwargs)

    @staticmethod
    def _generate_appointment_code():
        max_id = Appointment.objects.aggregate(value=Max("id"))["value"] or 0
        next_number = max_id + 1

        while True:
            candidate = f"LH-{next_number:05d}"
            if not Appointment.objects.filter(appointment_code=candidate).exists():
                return candidate
            next_number += 1

    @property
    def appointment_date(self):
        return self.doctor_schedule.work_date

    @property
    def doctor(self):
        return self.doctor_schedule.doctor

    @property
    def is_waiting(self):
        return self.status == self.Status.CHECKED_IN

    def clean(self):
        super().clean()
        errors = {}

        if self.patient_id and not self.patient.is_active:
            errors["patient"] = "Bệnh nhân này đang ngưng hoạt động."

        if self.start_time and self.end_time and self.end_time <= self.start_time:
            errors["end_time"] = "Giờ kết thúc phải sau giờ bắt đầu."

        if self.doctor_schedule_id:
            schedule = self.doctor_schedule
            if schedule.status != DoctorSchedule.Status.REGISTERED:
                errors["doctor_schedule"] = "Chỉ có thể đặt lịch vào lịch trực đang đăng ký."

            if ClinicHoliday.objects.filter(date=schedule.work_date, is_active=True).exists():
                errors["doctor_schedule"] = "Không thể đặt lịch khám vào ngày nghỉ."

            if self.start_time and self.end_time:
                if self.start_time < schedule.shift.start_time or self.end_time > schedule.shift.end_time:
                    errors["start_time"] = "Thời gian khám phải nằm trong ca trực đã chọn."

                overlapping_appointment = (
                    Appointment.objects.filter(
                        doctor_schedule=schedule,
                        start_time__lt=self.end_time,
                        end_time__gt=self.start_time,
                    )
                    .exclude(status=self.Status.CANCELLED)
                    .exclude(pk=self.pk)
                    .exists()
                )
                if overlapping_appointment:
                    errors["start_time"] = "Bác sĩ đã có lịch khám trùng thời gian."

                if self.patient_id:
                    overlapping_patient_appointment = (
                        Appointment.objects.filter(
                            patient=self.patient,
                            doctor_schedule__work_date=schedule.work_date,
                            start_time__lt=self.end_time,
                            end_time__gt=self.start_time,
                        )
                        .exclude(status=self.Status.CANCELLED)
                        .exclude(pk=self.pk)
                        .exists()
                    )
                    if overlapping_patient_appointment:
                        errors["patient"] = "Bệnh nhân đã có lịch khám trùng thời gian."

        if errors:
            raise ValidationError(errors)


class Invoice(TimestampedModel):
    class PaymentType(models.TextChoices):
        ONE_TIME = "one_time", "Thanh toán một lần"
        INSTALLMENT = "installment", "Trả góp"

    class Status(models.TextChoices):
        UNPAID = "unpaid", "Chưa thanh toán"
        PAID = "paid", "Đã thanh toán"
        OUTSTANDING = "outstanding", "Còn nợ"

    invoice_code = models.CharField("Mã hóa đơn", max_length=30, unique=True, blank=True)
    patient = models.ForeignKey(
        Patient,
        verbose_name="Bệnh nhân",
        on_delete=models.PROTECT,
        related_name="invoices",
    )
    appointment = models.ForeignKey(
        Appointment,
        verbose_name="Lịch khám",
        on_delete=models.SET_NULL,
        related_name="invoices",
        blank=True,
        null=True,
    )
    issue_date = models.DateField("Ngày lập", default=timezone.localdate)
    due_date = models.DateField("Ngày hẹn thanh toán", blank=True, null=True)
    payment_type = models.CharField(
        "Hình thức thanh toán",
        max_length=20,
        choices=PaymentType.choices,
        default=PaymentType.ONE_TIME,
    )
    total_amount = models.DecimalField(
        "Tổng chi phí",
        max_digits=14,
        decimal_places=0,
        default=Decimal("0"),
        editable=False,
        validators=[MinValueValidator(Decimal("0"))],
    )
    paid_amount = models.DecimalField(
        "Đã thanh toán",
        max_digits=14,
        decimal_places=0,
        default=Decimal("0"),
        editable=False,
        validators=[MinValueValidator(Decimal("0"))],
    )
    status = models.CharField(
        "Trạng thái",
        max_length=20,
        choices=Status.choices,
        default=Status.UNPAID,
        editable=False,
    )
    note = models.TextField("Ghi chú", blank=True)

    class Meta:
        ordering = ["-issue_date", "-id"]
        verbose_name = "Hóa đơn"
        verbose_name_plural = "Hóa đơn"

    def __str__(self):
        return f"{self.invoice_code} - {self.patient.full_name}" if self.invoice_code else self.patient.full_name

    def save(self, *args, **kwargs):
        if not self.invoice_code:
            self.invoice_code = self._generate_invoice_code()
        super().save(*args, **kwargs)

    @staticmethod
    def _generate_invoice_code():
        max_id = Invoice.objects.aggregate(value=Max("id"))["value"] or 0
        next_number = max_id + 1

        while True:
            candidate = f"HD-{next_number:05d}"
            if not Invoice.objects.filter(invoice_code=candidate).exists():
                return candidate
            next_number += 1

    def clean(self):
        super().clean()
        errors = {}

        if self.patient_id and not self.patient.is_active:
            errors["patient"] = "Bệnh nhân này đang ngưng hoạt động."

        if self.appointment_id and self.patient_id and self.appointment.patient_id != self.patient_id:
            errors["appointment"] = "Lịch khám không thuộc bệnh nhân đã chọn."

        if self.due_date and self.issue_date and self.due_date < self.issue_date:
            errors["due_date"] = "Ngày hẹn thanh toán không được trước ngày lập hóa đơn."

        if errors:
            raise ValidationError(errors)

    @property
    def outstanding_amount(self):
        value = self.total_amount - self.paid_amount
        return value if value > 0 else Decimal("0")

    def recalculate(self, save=True):
        if not self.pk:
            return

        total_amount = self.items.aggregate(total=Sum("line_total"))["total"] or Decimal("0")
        paid_amount = self.payments.aggregate(total=Sum("amount"))["total"] or Decimal("0")

        if paid_amount > 0 and paid_amount >= total_amount:
            status = self.Status.PAID
        elif paid_amount > 0:
            status = self.Status.OUTSTANDING
        else:
            status = self.Status.UNPAID

        self.total_amount = total_amount
        self.paid_amount = paid_amount
        self.status = status

        if save:
            Invoice.objects.filter(pk=self.pk).update(
                total_amount=total_amount,
                paid_amount=paid_amount,
                status=status,
                updated_at=timezone.now(),
            )


class InvoiceItem(TimestampedModel):
    invoice = models.ForeignKey(
        Invoice,
        verbose_name="Hóa đơn",
        on_delete=models.CASCADE,
        related_name="items",
    )
    service = models.ForeignKey(
        Service,
        verbose_name="Dịch vụ",
        on_delete=models.PROTECT,
        related_name="invoice_items",
        blank=True,
        null=True,
    )
    description = models.CharField("Nội dung điều trị", max_length=255, blank=True)
    quantity = models.PositiveIntegerField(
        "Số lượng",
        default=1,
        validators=[MinValueValidator(1)],
    )
    unit_price = models.DecimalField(
        "Đơn giá",
        max_digits=12,
        decimal_places=0,
        validators=[MinValueValidator(Decimal("0"))],
    )
    line_total = models.DecimalField(
        "Thành tiền",
        max_digits=14,
        decimal_places=0,
        default=Decimal("0"),
        editable=False,
        validators=[MinValueValidator(Decimal("0"))],
    )
    note = models.CharField("Ghi chú", max_length=255, blank=True)

    class Meta:
        ordering = ["id"]
        verbose_name = "Chi tiết hóa đơn"
        verbose_name_plural = "Chi tiết hóa đơn"

    def __str__(self):
        return f"{self.invoice.invoice_code} - {self.description or self.service}"

    def clean(self):
        super().clean()
        if not self.service_id and not self.description:
            raise ValidationError({"description": "Nhập nội dung điều trị hoặc chọn dịch vụ."})

    def save(self, *args, **kwargs):
        if self.service_id and not self.description:
            self.description = self.service.name
        self.line_total = self.unit_price * self.quantity
        super().save(*args, **kwargs)
        self.invoice.recalculate()

    def delete(self, *args, **kwargs):
        invoice = self.invoice
        result = super().delete(*args, **kwargs)
        invoice.recalculate()
        return result


class Payment(TimestampedModel):
    class Method(models.TextChoices):
        CASH = "cash", "Tiền mặt"
        TRANSFER = "transfer", "Chuyển khoản"
        CARD = "card", "Thẻ"
        MOMO = "momo", "MoMo"
        OTHER = "other", "Khác"

    invoice = models.ForeignKey(
        Invoice,
        verbose_name="Hóa đơn",
        on_delete=models.CASCADE,
        related_name="payments",
    )
    paid_at = models.DateField("Ngày thanh toán", default=timezone.localdate)
    amount = models.DecimalField(
        "Số tiền",
        max_digits=14,
        decimal_places=0,
        validators=[MinValueValidator(Decimal("1"))],
    )
    method = models.CharField("Phương thức", max_length=20, choices=Method.choices, default=Method.CASH)
    note = models.CharField("Ghi chú", max_length=255, blank=True)

    class Meta:
        ordering = ["-paid_at", "-id"]
        verbose_name = "Thanh toán"
        verbose_name_plural = "Thanh toán"

    def __str__(self):
        return f"{self.invoice.invoice_code} - {self.amount:,.0f}"

    def clean(self):
        super().clean()
        errors = {}

        if self.invoice_id and self.amount:
            paid_before = (
                Payment.objects.filter(invoice=self.invoice)
                .exclude(pk=self.pk)
                .aggregate(total=Sum("amount"))["total"]
                or Decimal("0")
            )
            if self.invoice.total_amount and paid_before + self.amount > self.invoice.total_amount:
                errors["amount"] = "Số tiền thanh toán vượt quá số tiền còn lại của hóa đơn."

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        self.invoice.recalculate()

    def delete(self, *args, **kwargs):
        invoice = self.invoice
        result = super().delete(*args, **kwargs)
        invoice.recalculate()
        return result


class PaymentTransaction(TimestampedModel):
    class Provider(models.TextChoices):
        MOMO = "momo", "MoMo"

    class Status(models.TextChoices):
        PENDING = "pending", "Đang chờ"
        SUCCESS = "success", "Thành công"
        FAILED = "failed", "Thất bại"
        REVIEW = "review", "Cần kiểm tra"

    invoice = models.ForeignKey(
        Invoice,
        verbose_name="Hóa đơn",
        on_delete=models.CASCADE,
        related_name="payment_transactions",
    )
    payment = models.OneToOneField(
        Payment,
        verbose_name="Thanh toán đã ghi nhận",
        on_delete=models.SET_NULL,
        related_name="payment_transaction",
        blank=True,
        null=True,
    )
    provider = models.CharField(
        "Cổng thanh toán",
        max_length=20,
        choices=Provider.choices,
        default=Provider.MOMO,
    )
    status = models.CharField(
        "Trạng thái giao dịch",
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )
    order_id = models.CharField("Mã giao dịch đối tác", max_length=80, unique=True)
    request_id = models.CharField("Mã request", max_length=80, unique=True)
    amount = models.DecimalField(
        "Số tiền",
        max_digits=14,
        decimal_places=0,
        validators=[MinValueValidator(Decimal("1"))],
    )
    customer_email = models.EmailField("Email nhận biên nhận", blank=True)
    pay_url = models.URLField("Liên kết thanh toán", blank=True, max_length=500)
    deeplink = models.CharField("Deeplink", blank=True, max_length=500)
    qr_code_url = models.CharField("Dữ liệu QR", blank=True, max_length=1000)
    trans_id = models.CharField("Mã giao dịch MoMo", blank=True, max_length=80)
    result_code = models.IntegerField("Mã kết quả", blank=True, null=True)
    provider_message = models.CharField("Thông điệp cổng thanh toán", blank=True, max_length=255)
    raw_create_response = models.JSONField("Phản hồi tạo giao dịch", blank=True, default=dict)
    raw_ipn_payload = models.JSONField("Payload IPN", blank=True, default=dict)
    redirect_payload = models.JSONField("Payload redirect", blank=True, default=dict)
    paid_at = models.DateTimeField("Thời điểm thanh toán thành công", blank=True, null=True)
    receipt_email_sent_at = models.DateTimeField("Thời điểm gửi mail biên nhận", blank=True, null=True)
    receipt_email_error = models.TextField("Lỗi gửi mail", blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        verbose_name = "Giao dịch cổng thanh toán"
        verbose_name_plural = "Giao dịch cổng thanh toán"

    def __str__(self):
        return f"{self.get_provider_display()} - {self.order_id} - {self.amount:,.0f}"


class Medicine(TimestampedModel):
    medicine_code = models.CharField("Mã thuốc", max_length=30, unique=True, blank=True)
    name = models.CharField("Tên thuốc", max_length=150)
    active_ingredient = models.CharField("Hoạt chất", max_length=150, blank=True)
    strength = models.CharField("Hàm lượng", max_length=80, blank=True)
    unit = models.CharField("Đơn vị", max_length=40, blank=True)
    usage_note = models.TextField("Hướng dẫn chung", blank=True)
    is_active = models.BooleanField("Đang sử dụng", default=True)

    class Meta:
        ordering = ["name", "strength"]
        unique_together = [("name", "strength")]
        verbose_name = "Thuốc"
        verbose_name_plural = "Thuốc"

    def __str__(self):
        details = f" {self.strength}" if self.strength else ""
        return f"{self.medicine_code} - {self.name}{details}" if self.medicine_code else f"{self.name}{details}"

    def save(self, *args, **kwargs):
        if not self.medicine_code:
            self.medicine_code = self._generate_medicine_code()
        super().save(*args, **kwargs)

    @staticmethod
    def _generate_medicine_code():
        max_id = Medicine.objects.aggregate(value=Max("id"))["value"] or 0
        next_number = max_id + 1

        while True:
            candidate = f"TH-{next_number:05d}"
            if not Medicine.objects.filter(medicine_code=candidate).exists():
                return candidate
            next_number += 1


class Supply(TimestampedModel):
    class Category(models.TextChoices):
        CONSUMABLE = "consumable", "Vật tư tiêu hao"
        INJECTION = "injection", "Kim tiêm / gây tê"
        MEDICINE = "medicine", "Thuốc / dung dịch"
        RESTORATIVE = "restorative", "Vật liệu phục hồi"
        STERILIZATION = "sterilization", "Khử khuẩn"
        INSTRUMENT = "instrument", "Dụng cụ"
        OTHER = "other", "Khác"

    supply_code = models.CharField("Mã vật tư", max_length=30, unique=True, blank=True)
    name = models.CharField("Tên vật tư", max_length=150)
    category = models.CharField(
        "Nhóm vật tư",
        max_length=30,
        choices=Category.choices,
        default=Category.CONSUMABLE,
    )
    unit = models.CharField("Đơn vị tính", max_length=40)
    minimum_quantity = models.DecimalField(
        "Ngưỡng cảnh báo tồn",
        max_digits=12,
        decimal_places=2,
        default=Decimal("0"),
        validators=[MinValueValidator(Decimal("0"))],
    )
    description = models.TextField("Mô tả", blank=True)
    is_active = models.BooleanField("Đang sử dụng", default=True)

    class Meta:
        ordering = ["category", "name"]
        unique_together = [("name", "unit")]
        verbose_name = "Vật tư"
        verbose_name_plural = "Vật tư"

    def __str__(self):
        return f"{self.supply_code} - {self.name}" if self.supply_code else self.name

    def save(self, *args, **kwargs):
        if not self.supply_code:
            self.supply_code = self._generate_supply_code()
        super().save(*args, **kwargs)

    @staticmethod
    def _generate_supply_code():
        max_id = Supply.objects.aggregate(value=Max("id"))["value"] or 0
        next_number = max_id + 1

        while True:
            candidate = f"VT-{next_number:05d}"
            if not Supply.objects.filter(supply_code=candidate).exists():
                return candidate
            next_number += 1

    @property
    def total_quantity(self):
        if not self.pk:
            return Decimal("0")
        return self.lots.aggregate(total=Sum("current_quantity"))["total"] or Decimal("0")

    @property
    def is_low_stock(self):
        return self.minimum_quantity > 0 and self.total_quantity <= self.minimum_quantity


class SupplyLot(TimestampedModel):
    supply = models.ForeignKey(
        Supply,
        verbose_name="Vật tư",
        on_delete=models.PROTECT,
        related_name="lots",
    )
    lot_number = models.CharField("Số lô", max_length=80, blank=True)
    supplier = models.CharField("Nhà cung cấp", max_length=150, blank=True)
    received_date = models.DateField("Ngày nhập", default=timezone.localdate)
    expiry_date = models.DateField("Hạn sử dụng", blank=True, null=True)
    initial_quantity = models.DecimalField(
        "Số lượng nhập",
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
    )
    current_quantity = models.DecimalField(
        "Tồn hiện tại",
        max_digits=12,
        decimal_places=2,
        default=Decimal("0"),
        editable=False,
        validators=[MinValueValidator(Decimal("0"))],
    )
    unit_cost = models.DecimalField(
        "Đơn giá nhập",
        max_digits=12,
        decimal_places=0,
        default=Decimal("0"),
        validators=[MinValueValidator(Decimal("0"))],
    )
    note = models.TextField("Ghi chú", blank=True)

    class Meta:
        ordering = ["expiry_date", "received_date", "id"]
        verbose_name = "Lô vật tư"
        verbose_name_plural = "Lô vật tư"

    def __str__(self):
        lot_label = self.lot_number or f"Lô #{self.pk or 'mới'}"
        return f"{self.supply.name} - {lot_label}"

    def clean(self):
        super().clean()
        errors = {}

        if self.supply_id and not self.supply.is_active:
            errors["supply"] = "Vật tư này đang ngưng sử dụng."

        if self.expiry_date and self.received_date and self.expiry_date < self.received_date:
            errors["expiry_date"] = "Hạn sử dụng không được trước ngày nhập."

        if self.pk and self.initial_quantity is not None:
            old_lot = SupplyLot.objects.filter(pk=self.pk).first()
            if old_lot:
                exported_quantity = old_lot.initial_quantity - old_lot.current_quantity
                if self.initial_quantity < exported_quantity:
                    errors["initial_quantity"] = "Số lượng nhập không được nhỏ hơn số lượng đã xuất."

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        update_fields = kwargs.get("update_fields")
        should_recalculate_current = update_fields is None or "initial_quantity" in update_fields
        if self.pk and should_recalculate_current:
            old_lot = SupplyLot.objects.get(pk=self.pk)
            self.current_quantity = old_lot.current_quantity + (self.initial_quantity - old_lot.initial_quantity)
            if self.current_quantity < 0:
                raise ValidationError({"initial_quantity": "Số lượng nhập không được nhỏ hơn số lượng đã xuất."})
            if update_fields is not None and "current_quantity" not in update_fields:
                kwargs["update_fields"] = set(update_fields) | {"current_quantity"}
        elif not self.pk:
            self.current_quantity = self.initial_quantity
        super().save(*args, **kwargs)

    @property
    def exported_quantity(self):
        value = self.initial_quantity - self.current_quantity
        return value if value > 0 else Decimal("0")

    @property
    def is_expired(self):
        return bool(self.expiry_date and self.expiry_date < timezone.localdate())

    @property
    def is_expiring_soon(self):
        if not self.expiry_date or self.current_quantity <= 0:
            return False
        today = timezone.localdate()
        return today <= self.expiry_date <= today + timedelta(days=30)


class SupplyExport(TimestampedModel):
    lot = models.ForeignKey(
        SupplyLot,
        verbose_name="Lô vật tư",
        on_delete=models.PROTECT,
        related_name="exports",
    )
    export_date = models.DateField("Ngày xuất", default=timezone.localdate)
    quantity = models.DecimalField(
        "Số lượng xuất",
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
    )
    used_for = models.CharField("Mục đích sử dụng", max_length=255, blank=True)
    performed_by = models.ForeignKey(
        Staff,
        verbose_name="Người thực hiện",
        on_delete=models.SET_NULL,
        related_name="supply_exports",
        blank=True,
        null=True,
    )
    note = models.TextField("Ghi chú", blank=True)

    class Meta:
        ordering = ["-export_date", "-id"]
        verbose_name = "Phiếu xuất vật tư"
        verbose_name_plural = "Phiếu xuất vật tư"

    def __str__(self):
        return f"{self.lot.supply.name} - {self.quantity:g} {self.lot.supply.unit}"

    @property
    def supply(self):
        return self.lot.supply

    def clean(self):
        super().clean()
        errors = {}

        if self.lot_id:
            available_quantity = self.lot.current_quantity
            if self.pk:
                old_export = SupplyExport.objects.select_related("lot").filter(pk=self.pk).first()
                if old_export and old_export.lot_id == self.lot_id:
                    available_quantity += old_export.quantity

            if self.quantity and self.quantity > available_quantity:
                errors["quantity"] = "Số lượng xuất vượt quá tồn hiện tại của lô."

            if self.lot.is_expired:
                errors["lot"] = "Không thể xuất vật tư từ lô đã hết hạn sử dụng."

            if self.export_date and self.lot.received_date and self.export_date < self.lot.received_date:
                errors["export_date"] = "Ngày xuất không được trước ngày nhập kho."

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        with transaction.atomic():
            old_export = None
            if self.pk:
                old_export = SupplyExport.objects.select_related("lot").select_for_update().get(pk=self.pk)
                old_lot = SupplyLot.objects.select_for_update().get(pk=old_export.lot_id)
                old_lot.current_quantity += old_export.quantity
                old_lot.save(update_fields=["current_quantity", "updated_at"])

            lot = SupplyLot.objects.select_for_update().get(pk=self.lot_id)
            if self.quantity > lot.current_quantity:
                raise ValidationError({"quantity": "Số lượng xuất vượt quá tồn hiện tại của lô."})

            lot.current_quantity -= self.quantity
            lot.save(update_fields=["current_quantity", "updated_at"])
            super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        with transaction.atomic():
            lot = SupplyLot.objects.select_for_update().get(pk=self.lot_id)
            lot.current_quantity += self.quantity
            lot.save(update_fields=["current_quantity", "updated_at"])
            return super().delete(*args, **kwargs)


class Prescription(TimestampedModel):
    prescription_code = models.CharField("Mã đơn thuốc", max_length=30, unique=True, blank=True)
    patient = models.ForeignKey(
        Patient,
        verbose_name="Bệnh nhân",
        on_delete=models.PROTECT,
        related_name="prescriptions",
    )
    appointment = models.ForeignKey(
        Appointment,
        verbose_name="Lịch khám",
        on_delete=models.SET_NULL,
        related_name="prescriptions",
        blank=True,
        null=True,
    )
    doctor = models.ForeignKey(
        Staff,
        verbose_name="Bác sĩ kê đơn",
        on_delete=models.PROTECT,
        related_name="prescriptions",
        blank=True,
        null=True,
    )
    prescribed_at = models.DateField("Ngày kê đơn", default=timezone.localdate)
    diagnosis = models.CharField("Chẩn đoán", max_length=255, blank=True)
    note = models.TextField("Ghi chú", blank=True)

    class Meta:
        ordering = ["-prescribed_at", "-id"]
        verbose_name = "Đơn thuốc"
        verbose_name_plural = "Đơn thuốc"

    def __str__(self):
        return f"{self.prescription_code} - {self.patient.full_name}" if self.prescription_code else self.patient.full_name

    def save(self, *args, **kwargs):
        if not self.prescription_code:
            self.prescription_code = self._generate_prescription_code()
        super().save(*args, **kwargs)

    @staticmethod
    def _generate_prescription_code():
        max_id = Prescription.objects.aggregate(value=Max("id"))["value"] or 0
        next_number = max_id + 1

        while True:
            candidate = f"DT-{next_number:05d}"
            if not Prescription.objects.filter(prescription_code=candidate).exists():
                return candidate
            next_number += 1

    def clean(self):
        super().clean()
        errors = {}

        if self.patient_id and not self.patient.is_active:
            errors["patient"] = "Bệnh nhân này đang ngưng hoạt động."

        if self.appointment_id and self.patient_id and self.appointment.patient_id != self.patient_id:
            errors["appointment"] = "Lịch khám không thuộc bệnh nhân đã chọn."

        if self.doctor_id:
            if self.doctor.role != Staff.Role.DOCTOR:
                errors["doctor"] = "Chỉ nhân sự có chức danh bác sĩ mới được kê đơn."
            elif not self.doctor.is_active:
                errors["doctor"] = "Bác sĩ này đang ngưng làm việc."

        if errors:
            raise ValidationError(errors)


class PrescriptionItem(TimestampedModel):
    prescription = models.ForeignKey(
        Prescription,
        verbose_name="Đơn thuốc",
        on_delete=models.CASCADE,
        related_name="items",
    )
    medicine = models.ForeignKey(
        Medicine,
        verbose_name="Thuốc",
        on_delete=models.PROTECT,
        related_name="prescription_items",
    )
    dosage = models.CharField("Liều dùng", max_length=150)
    quantity = models.PositiveIntegerField(
        "Số lượng",
        validators=[MinValueValidator(1)],
    )
    instructions = models.TextField("Hướng dẫn sử dụng")
    note = models.CharField("Ghi chú", max_length=255, blank=True)

    class Meta:
        ordering = ["id"]
        verbose_name = "Chi tiết đơn thuốc"
        verbose_name_plural = "Chi tiết đơn thuốc"

    def __str__(self):
        return f"{self.prescription.prescription_code} - {self.medicine.name}"

    def clean(self):
        super().clean()
        if self.medicine_id and not self.medicine.is_active:
            raise ValidationError({"medicine": "Thuốc này đang ngưng sử dụng."})
