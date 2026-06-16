from decimal import Decimal

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models, transaction
from django.db.models import Max, Sum
from django.conf import settings
from django.utils import timezone

from apps.clinic.models import Appointment, DoctorSchedule, Staff


class TimestampedModel(models.Model):
    created_at = models.DateTimeField("Ngày tạo", auto_now_add=True)
    updated_at = models.DateTimeField("Ngày cập nhật", auto_now=True)

    class Meta:
        abstract = True


class SalaryConfig(TimestampedModel):
    """UC4.1 — Thiết lập mức tiền cơ bản cho một giờ làm việc."""

    hourly_rate = models.DecimalField(
        "Số tiền một giờ (VNĐ)",
        max_digits=12,
        decimal_places=0,
        validators=[MinValueValidator(Decimal("0"))],
        help_text="Mức tiền cơ bản trả cho 1 giờ quy đổi.",
    )
    effective_from = models.DateField(
        "Áp dụng từ",
        help_text="Cấu hình này có hiệu lực từ ngày đã chọn trở đi.",
    )
    note = models.TextField("Ghi chú", blank=True)

    class Meta:
        ordering = ["-effective_from"]
        verbose_name = "Cấu hình lương cơ bản"
        verbose_name_plural = "Cấu hình lương cơ bản"

    def __str__(self):
        return f"{self.effective_from:%m/%Y} — {self.hourly_rate:,.0f} VNĐ/giờ"

    @classmethod
    def get_active_for_date(cls, target_date):
        """Trả về cấu hình lương hiệu lực tại ngày target_date."""
        return (
            cls.objects.filter(effective_from__lte=target_date)
            .order_by("-effective_from")
            .first()
        )


class AppointmentComplexity(TimestampedModel):
    """UC4.3 — Hệ số độ khó xử lý của một lượt khám cụ thể.

    Tổng_hệ_số_bệnh_nhân của một ca trực =
        SUM(complexity_coefficient) của tất cả Appointment
        thuộc DoctorSchedule đó (không tính CANCELLED).
    """

    appointment = models.OneToOneField(
        Appointment,
        verbose_name="Lượt khám",
        on_delete=models.CASCADE,
        related_name="complexity",
    )
    complexity_coefficient = models.DecimalField(
        "Hệ số phức tạp",
        max_digits=4,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00")), MaxValueValidator(Decimal("0.50"))],
        help_text="0.0 = thông thường; 0.1–0.5 = phức tạp.",
    )
    note = models.CharField("Lý do / ghi chú", max_length=255, blank=True)
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="Người nhập",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="recorded_complexities",
    )

    class Meta:
        ordering = ["-appointment__doctor_schedule__work_date"]
        verbose_name = "Hệ số ca phức tạp"
        verbose_name_plural = "Hệ số ca phức tạp"

    def __str__(self):
        return (
            f"{self.appointment.appointment_code} — "
            f"hệ số {self.complexity_coefficient}"
        )


class PaySlip(TimestampedModel):
    """UC4.4 — Phiếu lương tổng hợp cho một bác sĩ trong một tháng."""

    class Status(models.TextChoices):
        DRAFT = "draft", "Nháp"
        CONFIRMED = "confirmed", "Đã xác nhận"
        PAID = "paid", "Đã thanh toán"

    payslip_code = models.CharField(
        "Mã phiếu lương", max_length=30, unique=True, blank=True
    )
    doctor = models.ForeignKey(
        Staff,
        verbose_name="Bác sĩ",
        on_delete=models.PROTECT,
        related_name="payslips",
        limit_choices_to={"role": "doctor"},
    )
    month = models.PositiveSmallIntegerField(
        "Tháng",
        validators=[MinValueValidator(1), MaxValueValidator(12)],
    )
    year = models.PositiveSmallIntegerField(
        "Năm",
        validators=[MinValueValidator(2000), MaxValueValidator(2100)],
    )
    # Snapshot tại thời điểm lập phiếu
    hourly_rate = models.DecimalField(
        "Tiền một giờ (snapshot)",
        max_digits=12,
        decimal_places=0,
        validators=[MinValueValidator(Decimal("0"))],
    )
    doctor_coefficient = models.DecimalField(
        "Hệ số bác sĩ (snapshot)",
        max_digits=4,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.5")), MaxValueValidator(Decimal("5.0"))],
    )
    # Kết quả tính toán
    total_converted_hours = models.DecimalField(
        "Tổng giờ quy đổi",
        max_digits=10,
        decimal_places=4,
        default=Decimal("0"),
        editable=False,
    )
    total_amount = models.DecimalField(
        "Tổng tiền làm thêm (VNĐ)",
        max_digits=14,
        decimal_places=0,
        default=Decimal("0"),
        editable=False,
    )
    status = models.CharField(
        "Trạng thái",
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT,
    )
    note = models.TextField("Ghi chú", blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="Người lập phiếu",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_payslips",
    )

    class Meta:
        ordering = ["-year", "-month", "doctor__full_name"]
        unique_together = [("doctor", "month", "year")]
        verbose_name = "Phiếu lương"
        verbose_name_plural = "Phiếu lương"

    def __str__(self):
        return f"{self.payslip_code} — {self.doctor.full_name} {self.month:02d}/{self.year}"

    def save(self, *args, **kwargs):
        if not self.payslip_code:
            self.payslip_code = self._generate_code()
        super().save(*args, **kwargs)

    def _generate_code(self):
        max_id = PaySlip.objects.aggregate(value=Max("id"))["value"] or 0
        next_num = max_id + 1
        while True:
            candidate = f"PL-{self.year}{self.month:02d}-{next_num:04d}"
            if not PaySlip.objects.filter(payslip_code=candidate).exists():
                return candidate
            next_num += 1

    def recalculate(self, save=True):
        """Tính lại tổng từ các PaySlipEntry."""
        agg = self.entries.aggregate(
            hours=Sum("converted_hours"),
            amount=Sum("line_total"),
        )
        self.total_converted_hours = agg["hours"] or Decimal("0")
        self.total_amount = agg["amount"] or Decimal("0")
        if save:
            PaySlip.objects.filter(pk=self.pk).update(
                total_converted_hours=self.total_converted_hours,
                total_amount=self.total_amount,
                updated_at=timezone.now(),
            )


class PaySlipEntry(TimestampedModel):
    """Chi tiết lương cho từng ca trực trong PaySlip."""

    payslip = models.ForeignKey(
        PaySlip,
        verbose_name="Phiếu lương",
        on_delete=models.CASCADE,
        related_name="entries",
    )
    doctor_schedule = models.ForeignKey(
        DoctorSchedule,
        verbose_name="Ca trực",
        on_delete=models.PROTECT,
        related_name="payslip_entries",
    )
    # Snapshot tại thời điểm lập
    shift_hours = models.DecimalField(
        "Số giờ ca trực",
        max_digits=6,
        decimal_places=4,
        validators=[MinValueValidator(Decimal("0"))],
    )
    shift_coefficient = models.DecimalField(
        "Hệ số ca (snapshot)",
        max_digits=4,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("1.0")), MaxValueValidator(Decimal("2.0"))],
    )
    patient_coefficient_total = models.DecimalField(
        "Tổng hệ số bệnh nhân",
        max_digits=6,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0"))],
    )
    # Kết quả tính toán
    converted_hours = models.DecimalField(
        "Giờ quy đổi",
        max_digits=8,
        decimal_places=4,
        default=Decimal("0"),
    )
    line_total = models.DecimalField(
        "Thành tiền (VNĐ)",
        max_digits=14,
        decimal_places=0,
        default=Decimal("0"),
    )

    class Meta:
        ordering = ["doctor_schedule__work_date", "doctor_schedule__shift__start_time"]
        verbose_name = "Chi tiết phiếu lương"
        verbose_name_plural = "Chi tiết phiếu lương"

    def __str__(self):
        return (
            f"{self.payslip.payslip_code} — "
            f"{self.doctor_schedule.work_date:%d/%m/%Y} "
            f"{self.doctor_schedule.shift.name}"
        )

    def compute(self, payslip=None):
        """Tính converted_hours và line_total từ các giá trị snapshot.
        
        Args:
            payslip: PaySlip instance (optional). Nếu None sẽ dùng self.payslip.
        """
        if payslip is None:
            payslip = self.payslip
        self.converted_hours = self.shift_hours * (
            self.shift_coefficient + self.patient_coefficient_total
        )
        self.line_total = (
            self.converted_hours
            * payslip.doctor_coefficient
            * payslip.hourly_rate
        ).quantize(Decimal("1"))
