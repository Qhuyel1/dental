"""
Tests cho apps/payroll — UC4 Tính lương bác sĩ.
Kiểm tra logic nghiệp vụ cốt lõi và tích hợp view.
"""

from datetime import date, time
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase, Client
from django.urls import reverse

from apps.clinic.models import (
    Appointment,
    DoctorSchedule,
    Patient,
    Staff,
    WorkShift,
)
from .models import (
    AppointmentComplexity,
    PaySlip,
    PaySlipEntry,
    SalaryConfig,
)
from .views import (
    _compute_patient_coefficient,
    _compute_shift_hours,
    generate_payslip,
)

User = get_user_model()


class ShiftHoursComputationTest(TestCase):
    """UC4 — Kiểm tra tính giờ ca từ start_time/end_time."""

    def _make_shift(self, start_h, start_m, end_h, end_m):
        """Tạo WorkShift giả để test (không lưu DB, chỉ gán thuộc tính)."""
        class FakeShift:
            pass
        s = FakeShift()
        s.start_time = time(start_h, start_m)
        s.end_time = time(end_h, end_m)
        return s

    def test_standard_4_hour_shift(self):
        shift = self._make_shift(8, 0, 12, 0)
        result = _compute_shift_hours(shift)
        self.assertEqual(result, Decimal("4.0000"))

    def test_90_minute_shift(self):
        shift = self._make_shift(13, 0, 14, 30)
        result = _compute_shift_hours(shift)
        self.assertEqual(result, Decimal("1.5000"))

    def test_fractional_shift(self):
        shift = self._make_shift(7, 30, 11, 45)
        result = _compute_shift_hours(shift)
        # 4 giờ 15 phút = 4.25 giờ
        self.assertEqual(result, Decimal("4.25"))


class PaySlipEntryComputeTest(TestCase):
    """Kiểm tra công thức tính PaySlipEntry.compute()."""

    def _make_entry(self, shift_hours, shift_coeff, patient_coeff, doctor_coeff, hourly_rate):
        """Tạo PaySlipEntry + fake payslip để test công thức (không lưu DB)."""
        entry = PaySlipEntry()
        entry.shift_hours = Decimal(str(shift_hours))
        entry.shift_coefficient = Decimal(str(shift_coeff))
        entry.patient_coefficient_total = Decimal(str(patient_coeff))
        fake_payslip = type("FakePaySlip", (), {
            "doctor_coefficient": doctor_coeff,
            "hourly_rate": hourly_rate,
        })()
        return entry, fake_payslip

    def test_basic_no_patient_coefficient(self):
        """
        ca 4h, hs_ca=1.0, hs_BN=0 → giờ_qd=4, line_total=4×1.3×150000=780000
        """
        entry, ps = self._make_entry(4, 1.0, 0, Decimal("1.3"), Decimal("150000"))
        entry.compute(payslip=ps)
        self.assertEqual(entry.converted_hours, Decimal("4.0000"))
        self.assertEqual(entry.line_total, Decimal("780000"))

    def test_with_patient_complexity(self):
        """
        ca 4h, hs_ca=1.2, hs_BN=0.3 → giờ_qd=4×1.5=6, line_total=6×1.5×200000=1800000
        """
        entry, ps = self._make_entry(4, 1.2, 0.3, Decimal("1.5"), Decimal("200000"))
        entry.compute(payslip=ps)
        self.assertEqual(entry.converted_hours, Decimal("6.0000"))
        self.assertEqual(entry.line_total, Decimal("1800000"))

    def test_high_coefficient_doctor(self):
        """
        ca 3h, hs_ca=1.5, hs_BN=0 → giờ_qd=4.5, line_total=4.5×2.5×100000=1125000
        """
        entry, ps = self._make_entry(3, 1.5, 0, Decimal("2.5"), Decimal("100000"))
        entry.compute(payslip=ps)
        self.assertEqual(entry.converted_hours, Decimal("4.5000"))
        self.assertEqual(entry.line_total, Decimal("1125000"))


class GeneratePaySlipIntegrationTest(TestCase):
    """Kiểm tra toàn bộ luồng generate_payslip()."""

    def setUp(self):
        self.user = User.objects.create_superuser(
            username="admin_test", password="pass1234", email="admin@test.com"
        )
        self.doctor = Staff.objects.create(
            full_name="Dr. Test",
            role=Staff.Role.DOCTOR,
            salary_coefficient=Decimal("1.5"),
            is_active=True,
        )
        self.shift = WorkShift.objects.create(
            name="Ca sáng T2",
            weekday=0,  # Monday
            start_time=time(8, 0),
            end_time=time(12, 0),
            shift_coefficient=Decimal("1.0"),
        )
        self.salary_config = SalaryConfig.objects.create(
            hourly_rate=Decimal("150000"),
            effective_from=date(2024, 1, 1),
        )
        # Tạo lịch trực cho tháng 6/2026 (Monday 2026-06-01)
        self.schedule = DoctorSchedule.objects.create(
            doctor=self.doctor,
            work_date=date(2026, 6, 2),  # Monday
            shift=self.shift,
            status=DoctorSchedule.Status.REGISTERED,
        )

    def test_generate_creates_payslip_and_entries(self):
        payslip, entries, error = generate_payslip(
            doctor=self.doctor,
            month=6,
            year=2026,
            created_by=self.user,
        )
        self.assertIsNone(error)
        self.assertIsNotNone(payslip)
        self.assertEqual(len(entries), 1)
        self.assertEqual(payslip.doctor, self.doctor)
        self.assertEqual(payslip.month, 6)
        self.assertEqual(payslip.year, 2026)
        # Kiểm tra snapshot
        self.assertEqual(payslip.hourly_rate, Decimal("150000"))
        self.assertEqual(payslip.doctor_coefficient, Decimal("1.5"))

    def test_generate_calculates_correct_amount(self):
        """4h × (1.0+0) × 1.5 × 150000 = 900000"""
        payslip, _, error = generate_payslip(
            doctor=self.doctor, month=6, year=2026, created_by=self.user
        )
        self.assertIsNone(error)
        self.assertEqual(payslip.total_amount, Decimal("900000"))

    def test_generate_with_complexity_adds_patient_coefficient(self):
        """
        Tạo appointment + complexity=0.3 →
        4h × (1.0+0.3) × 1.5 × 150000 = 1170000
        """
        patient = Patient.objects.create(
            full_name="Bệnh nhân Test",
            date_of_birth=date(1990, 1, 1),
            gender="male",
        )
        appointment = Appointment(
            patient=patient,
            doctor_schedule=self.schedule,
            start_time=time(8, 0),
            end_time=time(9, 0),
            arrival_type=Appointment.ArrivalType.WALK_IN,
        )
        # skip clean() để tránh validate phức tạp trong test
        Appointment.objects.bulk_create([appointment])
        appointment = Appointment.objects.filter(doctor_schedule=self.schedule).first()
        AppointmentComplexity.objects.create(
            appointment=appointment,
            complexity_coefficient=Decimal("0.30"),
        )
        payslip, _, error = generate_payslip(
            doctor=self.doctor, month=6, year=2026, created_by=self.user
        )
        self.assertIsNone(error)
        expected = Decimal("4") * (Decimal("1.0") + Decimal("0.30")) * Decimal("1.5") * Decimal("150000")
        self.assertEqual(payslip.total_amount, expected.quantize(Decimal("1")))

    def test_generate_returns_error_without_salary_config(self):
        SalaryConfig.objects.all().delete()
        payslip, _, error = generate_payslip(
            doctor=self.doctor, month=6, year=2026
        )
        self.assertIsNone(payslip)
        self.assertIsNotNone(error)
        self.assertIn("cấu hình lương", error.lower())

    def test_generate_returns_error_when_no_schedules(self):
        _, _, error = generate_payslip(
            doctor=self.doctor, month=5, year=2026
        )
        self.assertIsNotNone(error)
        self.assertIn("không có ca trực", error.lower())

    def test_duplicate_payslip_rejected(self):
        generate_payslip(doctor=self.doctor, month=6, year=2026, created_by=self.user)
        # Gọi lần 2 sẽ bị reject bởi form (unique_together trong DB)
        self.assertTrue(
            PaySlip.objects.filter(doctor=self.doctor, month=6, year=2026).exists()
        )


class SalaryConfigTest(TestCase):
    """Kiểm tra lấy SalaryConfig đúng theo ngày hiệu lực."""

    def setUp(self):
        SalaryConfig.objects.create(hourly_rate=Decimal("100000"), effective_from=date(2024, 1, 1))
        SalaryConfig.objects.create(hourly_rate=Decimal("150000"), effective_from=date(2025, 1, 1))
        SalaryConfig.objects.create(hourly_rate=Decimal("200000"), effective_from=date(2026, 6, 1))

    def test_get_latest_before_date(self):
        config = SalaryConfig.get_active_for_date(date(2025, 6, 15))
        self.assertEqual(config.hourly_rate, Decimal("150000"))

    def test_get_exact_date(self):
        config = SalaryConfig.get_active_for_date(date(2026, 6, 1))
        self.assertEqual(config.hourly_rate, Decimal("200000"))

    def test_before_any_config_returns_none(self):
        config = SalaryConfig.get_active_for_date(date(2023, 12, 31))
        self.assertIsNone(config)
