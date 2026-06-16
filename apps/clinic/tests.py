from datetime import date, datetime, time, timedelta
from decimal import Decimal
import json
from unittest.mock import patch

from django.contrib.auth.models import Group, User
from django.core import mail
from django.core.exceptions import ValidationError
from django.test import RequestFactory
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.users.models import get_user_security_profile
from apps.users.roles import ROLE_ASSISTANT, ROLE_DOCTOR, sync_role_groups

from .forms import (
    AppointmentForm,
    DoctorScheduleForm,
    InvoiceItemForm,
    MoMoPaymentForm,
    PatientForm,
    PaymentForm,
    PrescriptionItemForm,
    ServiceForm,
    ServicePriceForm,
    SupplyExportForm,
    SupplyLotForm,
)
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
from .views import AppointmentCreateView, make_momo_signature, send_invoice_receipt_email


def make_patient(name="Nguyen Van Benh", **kwargs):
    defaults = {"full_name": name}
    defaults.update(kwargs)
    return Patient.objects.create(**defaults)


def make_staff(name="Le Thi Bac Si", role=Staff.Role.DOCTOR, **kwargs):
    defaults = {"full_name": name, "role": role}
    defaults.update(kwargs)
    return Staff.objects.create(**defaults)


def make_shift(
    name=None,
    weekday=WorkShift.Weekday.MONDAY,
    start_time=time(8, 0),
    end_time=time(12, 0),
    **kwargs,
):
    if name is None:
        name = f"Ca test {WorkShift.objects.count() + 1}"
    defaults = {
        "name": name,
        "weekday": weekday,
        "start_time": start_time,
        "end_time": end_time,
    }
    defaults.update(kwargs)
    return WorkShift.objects.create(**defaults)


def make_schedule(doctor=None, work_date=date(2026, 5, 4), shift=None, **kwargs):
    doctor = doctor or make_staff()
    shift = shift or make_shift(weekday=work_date.weekday())
    defaults = {"doctor": doctor, "work_date": work_date, "shift": shift}
    defaults.update(kwargs)
    return DoctorSchedule.objects.create(**defaults)


def make_service(name="Khám răng", category=None, **kwargs):
    category = category or ServiceCategory.objects.create(name=f"Danh mục test {ServiceCategory.objects.count() + 1}")
    defaults = {"category": category, "name": name}
    defaults.update(kwargs)
    return Service.objects.create(**defaults)


def make_price_list(name="Bảng giá 2026", **kwargs):
    defaults = {"name": name, "effective_from": date(2026, 1, 1)}
    defaults.update(kwargs)
    return PriceList.objects.create(**defaults)


def make_appointment(
    patient=None,
    doctor_schedule=None,
    start_time=time(9, 0),
    end_time=time(9, 30),
    **kwargs,
):
    patient = patient or make_patient()
    doctor_schedule = doctor_schedule or make_schedule()
    defaults = {
        "patient": patient,
        "doctor_schedule": doctor_schedule,
        "start_time": start_time,
        "end_time": end_time,
    }
    defaults.update(kwargs)
    return Appointment.objects.create(**defaults)


def make_invoice(patient=None, **kwargs):
    patient = patient or make_patient()
    defaults = {"patient": patient, "issue_date": date(2026, 5, 13)}
    defaults.update(kwargs)
    return Invoice.objects.create(**defaults)


def make_medicine(name="Amoxicillin", **kwargs):
    defaults = {"name": name, "strength": "500mg", "unit": "viên"}
    defaults.update(kwargs)
    return Medicine.objects.create(**defaults)


def make_supply(name="Găng tay nitrile", **kwargs):
    defaults = {
        "name": name,
        "category": Supply.Category.CONSUMABLE,
        "unit": "hộp",
        "minimum_quantity": Decimal("5"),
    }
    defaults.update(kwargs)
    return Supply.objects.create(**defaults)


def make_supply_lot(supply=None, **kwargs):
    supply = supply or make_supply()
    defaults = {
        "supply": supply,
        "lot_number": f"LOT-{SupplyLot.objects.count() + 1}",
        "received_date": date(2026, 5, 13),
        "expiry_date": date(2027, 5, 13),
        "initial_quantity": Decimal("10"),
        "unit_cost": Decimal("100000"),
    }
    defaults.update(kwargs)
    return SupplyLot.objects.create(**defaults)


def make_prescription(patient=None, doctor=None, **kwargs):
    patient = patient or make_patient()
    doctor = doctor or make_staff()
    defaults = {"patient": patient, "doctor": doctor, "prescribed_at": date(2026, 5, 13)}
    defaults.update(kwargs)
    return Prescription.objects.create(**defaults)


class ClinicModelTests(TestCase):
    def test_patient_code_is_generated_and_age_is_calculated(self):
        today = timezone.localdate()
        patient = Patient.objects.create(
            full_name="Nguyen Van Tuoi",
            date_of_birth=date(today.year - 30, today.month, today.day),
        )

        self.assertTrue(patient.patient_code.startswith("BN-"))
        self.assertEqual(patient.age, 30)

    def test_staff_code_is_generated_when_blank(self):
        staff = Staff.objects.create(full_name="Nguyen Van A", role=Staff.Role.DOCTOR)

        self.assertTrue(staff.employee_code.startswith("BS-"))

    def test_non_doctor_staff_code_uses_employee_prefix(self):
        staff = Staff.objects.create(full_name="Le Thi Le Tan", role=Staff.Role.RECEPTIONIST)

        self.assertTrue(staff.employee_code.startswith("NV-"))

    def test_service_codes_are_generated_when_blank(self):
        category = ServiceCategory.objects.create(name="Khám tổng quát")
        service = Service.objects.create(category=category, name="Khám răng")

        self.assertTrue(category.code.startswith("DM-"))
        self.assertTrue(service.code.startswith("DV-"))

    def test_appointment_code_is_generated_when_blank(self):
        appointment = make_appointment()

        self.assertTrue(appointment.appointment_code.startswith("LH-"))

    def test_invoice_totals_and_status_are_recalculated(self):
        invoice = make_invoice()
        service = make_service(name="Cạo vôi răng")

        InvoiceItem.objects.create(invoice=invoice, service=service, quantity=2, unit_price=500000)
        invoice.refresh_from_db()

        self.assertTrue(invoice.invoice_code.startswith("HD-"))
        self.assertEqual(invoice.total_amount, Decimal("1000000"))
        self.assertEqual(invoice.paid_amount, Decimal("0"))
        self.assertEqual(invoice.status, Invoice.Status.UNPAID)
        self.assertEqual(invoice.outstanding_amount, Decimal("1000000"))

        Payment.objects.create(invoice=invoice, amount=400000, method=Payment.Method.CASH)
        invoice.refresh_from_db()
        self.assertEqual(invoice.status, Invoice.Status.OUTSTANDING)
        self.assertEqual(invoice.outstanding_amount, Decimal("600000"))

        Payment.objects.create(invoice=invoice, amount=600000, method=Payment.Method.TRANSFER)
        invoice.refresh_from_db()
        self.assertEqual(invoice.status, Invoice.Status.PAID)
        self.assertEqual(invoice.outstanding_amount, Decimal("0"))

    def test_payment_rejects_amount_greater_than_remaining_invoice_balance(self):
        invoice = make_invoice()
        InvoiceItem.objects.create(invoice=invoice, description="Điều trị", quantity=1, unit_price=500000)
        invoice.refresh_from_db()
        payment = Payment(invoice=invoice, amount=600000)

        with self.assertRaises(ValidationError):
            payment.full_clean()

    def test_medicine_and_prescription_codes_are_generated(self):
        medicine = make_medicine(name="Ibuprofen")
        prescription = make_prescription()

        self.assertTrue(medicine.medicine_code.startswith("TH-"))
        self.assertTrue(prescription.prescription_code.startswith("DT-"))

    def test_supply_lot_tracks_stock_and_low_stock_alert(self):
        supply = make_supply(name="Kim tiêm nha khoa", minimum_quantity=Decimal("8"))
        lot = make_supply_lot(supply=supply, initial_quantity=Decimal("10"))

        self.assertTrue(supply.supply_code.startswith("VT-"))
        self.assertEqual(lot.current_quantity, Decimal("10"))
        self.assertFalse(supply.is_low_stock)

        SupplyExport.objects.create(lot=lot, quantity=Decimal("3"), export_date=date(2026, 5, 13))
        lot.refresh_from_db()
        self.assertEqual(lot.current_quantity, Decimal("7.00"))
        self.assertTrue(supply.is_low_stock)

    def test_supply_export_rejects_quantity_greater_than_current_stock(self):
        lot = make_supply_lot(initial_quantity=Decimal("4"))
        export = SupplyExport(lot=lot, quantity=Decimal("5"), export_date=date(2026, 5, 13))

        with self.assertRaises(ValidationError):
            export.full_clean()

    def test_supply_export_restores_stock_when_deleted(self):
        lot = make_supply_lot(initial_quantity=Decimal("10"))
        export = SupplyExport.objects.create(lot=lot, quantity=Decimal("4"), export_date=date(2026, 5, 13))
        lot.refresh_from_db()
        self.assertEqual(lot.current_quantity, Decimal("6.00"))

        export.delete()
        lot.refresh_from_db()
        self.assertEqual(lot.current_quantity, Decimal("10.00"))

    def test_supply_export_rejects_expired_lot(self):
        lot = make_supply_lot(expiry_date=date(2026, 1, 1))
        export = SupplyExport(lot=lot, quantity=Decimal("1"), export_date=date(2026, 5, 13))

        with self.assertRaises(ValidationError):
            export.full_clean()

    def test_prescription_rejects_appointment_for_other_patient(self):
        patient = make_patient(name="Benh nhan A")
        other_patient = make_patient(name="Benh nhan B")
        appointment = make_appointment(patient=patient)
        prescription = Prescription(patient=other_patient, appointment=appointment)

        with self.assertRaises(ValidationError):
            prescription.full_clean()

    def test_price_list_rejects_invalid_effective_range(self):
        price_list = PriceList(
            name="Bảng giá lỗi",
            effective_from=date(2026, 5, 2),
            effective_to=date(2026, 5, 1),
        )

        with self.assertRaises(ValidationError):
            price_list.full_clean()

    def test_work_shift_rejects_invalid_time_range(self):
        shift = WorkShift(
            name="Ca lỗi",
            weekday=WorkShift.Weekday.MONDAY,
            start_time=time(13, 0),
            end_time=time(8, 0),
        )

        with self.assertRaises(ValidationError):
            shift.full_clean()

    def test_work_shift_rejects_overlapping_active_shift(self):
        WorkShift.objects.create(
            name="Ca sáng",
            weekday=WorkShift.Weekday.MONDAY,
            start_time=time(8, 0),
            end_time=time(12, 0),
        )
        overlapping = WorkShift(
            name="Ca trùng",
            weekday=WorkShift.Weekday.MONDAY,
            start_time=time(11, 0),
            end_time=time(15, 0),
        )

        with self.assertRaises(ValidationError):
            overlapping.full_clean()

    def test_doctor_schedule_rejects_non_doctor_staff(self):
        receptionist = Staff.objects.create(full_name="Le Tan", role=Staff.Role.RECEPTIONIST)
        shift = WorkShift.objects.create(
            name="Ca chiều",
            weekday=WorkShift.Weekday.MONDAY,
            start_time=time(13, 0),
            end_time=time(17, 0),
        )
        schedule = DoctorSchedule(doctor=receptionist, work_date=date(2026, 5, 4), shift=shift)

        with self.assertRaises(ValidationError):
            schedule.full_clean()

    def test_doctor_schedule_rejects_shift_on_wrong_weekday(self):
        doctor = Staff.objects.create(full_name="Bac si sai ngay", role=Staff.Role.DOCTOR)
        tuesday_shift = WorkShift.objects.create(
            name="Ca thứ ba",
            weekday=WorkShift.Weekday.TUESDAY,
            start_time=time(8, 0),
            end_time=time(12, 0),
        )
        schedule = DoctorSchedule(doctor=doctor, work_date=date(2026, 5, 4), shift=tuesday_shift)

        with self.assertRaises(ValidationError):
            schedule.full_clean()

    def test_doctor_schedule_rejects_holiday(self):
        doctor = Staff.objects.create(full_name="Bac si truc", role=Staff.Role.DOCTOR)
        shift = WorkShift.objects.create(
            name="Ca sáng",
            weekday=WorkShift.Weekday.MONDAY,
            start_time=time(8, 0),
            end_time=time(12, 0),
        )
        ClinicHoliday.objects.create(date=date(2026, 5, 4), name="Nghỉ lễ")
        schedule = DoctorSchedule(doctor=doctor, work_date=date(2026, 5, 4), shift=shift)

        with self.assertRaises(ValidationError):
            schedule.full_clean()

    def test_appointment_rejects_overlapping_doctor_time(self):
        doctor = Staff.objects.create(full_name="Bac si kham", role=Staff.Role.DOCTOR)
        patient = Patient.objects.create(full_name="Nguyen Van Benh")
        other_patient = Patient.objects.create(full_name="Tran Thi Benh")
        shift = WorkShift.objects.create(
            name="Ca sáng",
            weekday=WorkShift.Weekday.MONDAY,
            start_time=time(8, 0),
            end_time=time(12, 0),
        )
        schedule = DoctorSchedule.objects.create(doctor=doctor, work_date=date(2026, 5, 4), shift=shift)
        Appointment.objects.create(
            patient=patient,
            doctor_schedule=schedule,
            start_time=time(8, 0),
            end_time=time(8, 30),
        )
        overlapping = Appointment(
            patient=other_patient,
            doctor_schedule=schedule,
            start_time=time(8, 15),
            end_time=time(8, 45),
        )

        with self.assertRaises(ValidationError):
            overlapping.full_clean()

    def test_appointment_rejects_overlapping_patient_time(self):
        doctor = Staff.objects.create(full_name="Bac si A", role=Staff.Role.DOCTOR)
        other_doctor = Staff.objects.create(full_name="Bac si B", role=Staff.Role.DOCTOR)
        patient = Patient.objects.create(full_name="Nguyen Van Trung")
        shift = WorkShift.objects.create(
            name="Ca sáng",
            weekday=WorkShift.Weekday.MONDAY,
            start_time=time(8, 0),
            end_time=time(12, 0),
        )
        schedule = DoctorSchedule.objects.create(doctor=doctor, work_date=date(2026, 5, 4), shift=shift)
        other_schedule = DoctorSchedule.objects.create(
            doctor=other_doctor,
            work_date=date(2026, 5, 4),
            shift=shift,
        )
        Appointment.objects.create(
            patient=patient,
            doctor_schedule=schedule,
            start_time=time(9, 0),
            end_time=time(9, 30),
        )
        overlapping = Appointment(
            patient=patient,
            doctor_schedule=other_schedule,
            start_time=time(9, 15),
            end_time=time(9, 45),
        )

        with self.assertRaises(ValidationError):
            overlapping.full_clean()

    def test_appointment_rejects_time_outside_shift(self):
        schedule = make_schedule()
        appointment = Appointment(
            patient=make_patient(),
            doctor_schedule=schedule,
            start_time=time(7, 30),
            end_time=time(8, 30),
        )

        with self.assertRaises(ValidationError):
            appointment.full_clean()

    def test_appointment_rejects_inactive_patient(self):
        schedule = make_schedule()
        appointment = Appointment(
            patient=make_patient(is_active=False),
            doctor_schedule=schedule,
            start_time=time(9, 0),
            end_time=time(9, 30),
        )

        with self.assertRaises(ValidationError):
            appointment.full_clean()


class ClinicFormTests(TestCase):
    def test_patient_form_creates_linked_user(self):
        data = {
            "full_name": "Nguyen Patient Test",
            "gender": Patient.Gender.MALE,
            "is_active": True,
            "create_login_account": True,
            "username": "patienttest123",
            "initial_password": "SecurePassword123!",
        }
        form = PatientForm(data=data)
        self.assertTrue(form.is_valid())
        patient = form.save()

        self.assertIsNotNone(patient.user)
        self.assertEqual(patient.user.username, "patienttest123")
        self.assertEqual(patient.user.first_name, patient.full_name)
        self.assertFalse(patient.user.is_staff)
        self.assertTrue(patient.user.is_active)
        self.assertTrue(patient.user.groups.filter(name="Bệnh nhân").exists())

    def test_service_form_only_lists_active_categories(self):
        active_category = ServiceCategory.objects.create(name="Đang dùng")
        inactive_category = ServiceCategory.objects.create(name="Ngưng dùng", is_active=False)

        form = ServiceForm()

        self.assertIn(active_category, form.fields["category"].queryset)
        self.assertNotIn(inactive_category, form.fields["category"].queryset)

    def test_doctor_schedule_form_only_lists_active_doctors(self):
        active_doctor = make_staff(name="Bac si dang lam", role=Staff.Role.DOCTOR)
        inactive_doctor = make_staff(name="Bac si nghi", role=Staff.Role.DOCTOR, is_active=False)
        receptionist = make_staff(name="Le tan", role=Staff.Role.RECEPTIONIST)

        form = DoctorScheduleForm()

        self.assertIn(active_doctor, form.fields["doctor"].queryset)
        self.assertNotIn(inactive_doctor, form.fields["doctor"].queryset)
        self.assertNotIn(receptionist, form.fields["doctor"].queryset)

    def test_doctor_schedule_form_saves_multiple_shifts(self):
        doctor = make_staff(role=Staff.Role.DOCTOR)
        shift1 = make_shift(name="Ca 1", weekday=WorkShift.Weekday.MONDAY, start_time=time(8, 0), end_time=time(12, 0))
        shift2 = make_shift(name="Ca 2", weekday=WorkShift.Weekday.MONDAY, start_time=time(13, 0), end_time=time(17, 0))
        
        data = {
            "doctor": doctor.pk,
            "work_date": "2026-05-04",
            "shifts": [shift1.pk, shift2.pk],
            "status": DoctorSchedule.Status.REGISTERED,
            "note": "Test bulk",
        }
        
        form = DoctorScheduleForm(data=data)
        self.assertTrue(form.is_valid())
        form.save()
        
        schedules = DoctorSchedule.objects.filter(doctor=doctor, work_date=date(2026, 5, 4))
        self.assertEqual(schedules.count(), 2)
        self.assertTrue(schedules.filter(shift=shift1).exists())
        self.assertTrue(schedules.filter(shift=shift2).exists())

    def test_doctor_schedule_form_validates_weekday(self):
        doctor = make_staff(role=Staff.Role.DOCTOR)
        shift_tuesday = make_shift(name="Ca Thứ Ba", weekday=WorkShift.Weekday.TUESDAY)
        
        data = {
            "doctor": doctor.pk,
            "work_date": "2026-05-04",
            "shifts": [shift_tuesday.pk],
            "status": DoctorSchedule.Status.REGISTERED,
        }
        
        form = DoctorScheduleForm(data=data)
        self.assertFalse(form.is_valid())
        self.assertIn("shifts", form.errors)

    def test_appointment_form_only_lists_active_and_registered_resources(self):
        active_patient = make_patient(name="Benh nhan active")
        inactive_patient = make_patient(name="Benh nhan inactive", is_active=False)
        active_service = make_service(name="Dich vu active")
        inactive_service = make_service(name="Dich vu inactive", is_active=False)
        registered_schedule = make_schedule()
        cancelled_schedule = make_schedule(
            doctor=make_staff(name="Bac si huy"),
            work_date=date(2026, 5, 5),
            shift=make_shift(weekday=WorkShift.Weekday.TUESDAY),
            status=DoctorSchedule.Status.CANCELLED,
        )

        form = AppointmentForm()

        self.assertIn(active_patient, form.fields["patient"].queryset)
        self.assertNotIn(inactive_patient, form.fields["patient"].queryset)
        self.assertIn(active_service, form.fields["service"].queryset)
        self.assertNotIn(inactive_service, form.fields["service"].queryset)
        self.assertIn(registered_schedule, form.fields["doctor_schedule"].queryset)
        self.assertNotIn(cancelled_schedule, form.fields["doctor_schedule"].queryset)
        self.assertIn("visit_type", form.fields)
        self.assertIn("priority_level", form.fields)

    def test_service_price_form_excludes_services_already_in_price_list(self):
        category = ServiceCategory.objects.create(name="Điều trị")
        priced_service = make_service(name="Trám răng", category=category)
        unpriced_service = make_service(name="Nhổ răng", category=category)
        price_list = make_price_list()
        ServicePrice.objects.create(price_list=price_list, service=priced_service, price=500000)

        form = ServicePriceForm(price_list=price_list)

        self.assertNotIn(priced_service, form.fields["service"].queryset)
        self.assertIn(unpriced_service, form.fields["service"].queryset)

    def test_invoice_item_form_only_lists_active_services(self):
        active_service = make_service(name="Dịch vụ hóa đơn active")
        inactive_service = make_service(name="Dịch vụ hóa đơn inactive", is_active=False)
        invoice = make_invoice()

        form = InvoiceItemForm(invoice=invoice)

        self.assertIn(active_service, form.fields["service"].queryset)
        self.assertNotIn(inactive_service, form.fields["service"].queryset)

    def test_payment_form_prefills_outstanding_amount(self):
        invoice = make_invoice()
        InvoiceItem.objects.create(invoice=invoice, description="Điều trị", quantity=1, unit_price=800000)
        invoice.refresh_from_db()

        form = PaymentForm(invoice=invoice)

        self.assertEqual(form.fields["amount"].initial, Decimal("800000"))

    def test_momo_payment_form_prefills_patient_email_and_rejects_amount_above_outstanding(self):
        patient = make_patient(name="Benh nhan momo form", email="patient@example.com")
        invoice = make_invoice(patient=patient)
        InvoiceItem.objects.create(invoice=invoice, description="Điều trị", quantity=1, unit_price=500000)
        invoice.refresh_from_db()

        form = MoMoPaymentForm(
            data={"amount": "600000", "customer_email": "patient@example.com"},
            invoice=invoice,
        )

        self.assertEqual(form.fields["amount"].initial, Decimal("500000"))
        self.assertEqual(form.fields["customer_email"].initial, "patient@example.com")
        self.assertFalse(form.is_valid())
        self.assertIn("amount", form.errors)

    def test_prescription_item_form_only_lists_active_medicines(self):
        active_medicine = make_medicine(name="Thuốc active")
        inactive_medicine = make_medicine(name="Thuốc inactive", is_active=False)
        prescription = make_prescription()

        form = PrescriptionItemForm(prescription=prescription)

        self.assertIn(active_medicine, form.fields["medicine"].queryset)
        self.assertNotIn(inactive_medicine, form.fields["medicine"].queryset)

    def test_supply_lot_form_only_lists_active_supplies(self):
        active_supply = make_supply(name="Vật tư active")
        inactive_supply = make_supply(name="Vật tư inactive", is_active=False)

        form = SupplyLotForm()

        self.assertIn(active_supply, form.fields["supply"].queryset)
        self.assertNotIn(inactive_supply, form.fields["supply"].queryset)

    def test_supply_export_form_only_lists_available_non_expired_lots(self):
        supply = make_supply(name="Vật tư xuất kho")
        available_lot = make_supply_lot(supply=supply, lot_number="OK", initial_quantity=Decimal("5"))
        empty_lot = make_supply_lot(
            supply=supply,
            lot_number="EMPTY",
            initial_quantity=Decimal("2"),
        )
        SupplyLot.objects.filter(pk=empty_lot.pk).update(current_quantity=Decimal("0"))
        empty_lot.refresh_from_db()
        expired_lot = make_supply_lot(
            supply=supply,
            lot_number="EXP",
            expiry_date=timezone.localdate() - timedelta(days=1),
        )

        form = SupplyExportForm(supply=supply)

        self.assertIn(available_lot, form.fields["lot"].queryset)
        self.assertNotIn(empty_lot, form.fields["lot"].queryset)
        self.assertNotIn(expired_lot, form.fields["lot"].queryset)

    def test_appointment_create_initial_uses_calendar_query_params(self):
        doctor = make_staff(name="Bac si calendar", role=Staff.Role.DOCTOR)
        shift = make_shift(
            weekday=WorkShift.Weekday.WEDNESDAY,
            start_time=time(8, 0),
            end_time=time(12, 0),
        )
        schedule = make_schedule(doctor=doctor, work_date=date(2026, 5, 13), shift=shift)
        request = RequestFactory().get(
            reverse("clinic:appointment-create"),
            {"date": "2026-05-13", "start_time": "09:30", "doctor": str(doctor.pk)},
        )
        view = AppointmentCreateView()
        view.request = request

        initial = view.get_initial()

        self.assertEqual(initial["doctor_schedule"], schedule)
        self.assertEqual(initial["start_time"], time(9, 30))
        self.assertEqual(initial["end_time"], time(10, 0))


@override_settings(ALLOWED_HOSTS=["testserver"])
class ClinicViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="admin",
            password="StrongPass123!",
            is_staff=True,
            is_superuser=True,
        )
        self.client.login(username="admin", password="StrongPass123!")

    def test_system_dashboard_renders_for_staff_user(self):
        response = self.client.get(reverse("clinic:dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Quản lý hệ thống")
        self.assertContains(response, "Báo cáo thống kê")
        self.assertContains(response, "Hiệu suất bác sĩ")

    def test_system_dashboard_report_widgets_render_with_data(self):
        today = timezone.localdate()
        doctor = make_staff(name="Bac si bao cao", role=Staff.Role.DOCTOR)
        patient = make_patient(name="Benh nhan bao cao")
        service = make_service(name="Dịch vụ báo cáo")
        shift = make_shift(
            weekday=today.weekday(),
            start_time=time(8, 0),
            end_time=time(12, 0),
        )
        schedule = make_schedule(doctor=doctor, work_date=today, shift=shift)
        appointment = make_appointment(
            patient=patient,
            doctor_schedule=schedule,
            service=service,
            start_time=time(8, 0),
            end_time=time(8, 30),
            status=Appointment.Status.COMPLETED,
        )
        make_appointment(
            patient=make_patient(name="Benh nhan huy lich"),
            doctor_schedule=schedule,
            service=service,
            start_time=time(9, 0),
            end_time=time(9, 30),
            status=Appointment.Status.CANCELLED,
        )
        invoice = Invoice.objects.create(patient=patient, appointment=appointment, issue_date=today)
        InvoiceItem.objects.create(invoice=invoice, service=service, quantity=2, unit_price=300000)
        Payment.objects.create(invoice=invoice, paid_at=today, amount=600000)

        response = self.client.get(reverse("clinic:dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Xu hướng doanh thu 14 ngày")
        self.assertContains(response, "Xu hướng lịch khám")
        self.assertContains(response, "Doanh thu 7 ngày")
        self.assertContains(response, "Dịch vụ được dùng nhiều nhất")
        self.assertContains(response, service.name)
        self.assertContains(response, doctor.full_name)

    def test_management_views_require_staff_user(self):
        self.client.logout()
        response = self.client.get(reverse("clinic:dashboard"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/system/users/login/", response["Location"])

        normal_user = User.objects.create_user(username="normal", password="StrongPass123!")
        self.client.login(username=normal_user.username, password="StrongPass123!")
        response = self.client.get(reverse("clinic:dashboard"))
        self.assertEqual(response.status_code, 403)

    def test_management_lists_render_for_staff_user(self):
        category = ServiceCategory.objects.create(name="Chỉnh nha")
        service = Service.objects.create(category=category, name="Tư vấn chỉnh nha")
        price_list = PriceList.objects.create(name="Bảng giá 2026", effective_from=date(2026, 1, 1))
        ServicePrice.objects.create(price_list=price_list, service=service, price=200000)
        doctor = Staff.objects.create(full_name="Le Thi Bac Si", role=Staff.Role.DOCTOR)
        patient = Patient.objects.create(full_name="Pham Van Benh")
        shift = WorkShift.objects.create(
            name="Ca sáng",
            weekday=WorkShift.Weekday.MONDAY,
            start_time=time(8, 0),
            end_time=time(12, 0),
        )
        doctor_schedule = DoctorSchedule.objects.create(
            doctor=doctor,
            work_date=date(2026, 5, 4),
            shift=shift,
        )
        Appointment.objects.create(
            patient=patient,
            doctor_schedule=doctor_schedule,
            service=service,
            start_time=time(9, 0),
            end_time=time(9, 30),
        )
        invoice = Invoice.objects.create(patient=patient, appointment=doctor_schedule.appointments.first())
        InvoiceItem.objects.create(invoice=invoice, service=service, quantity=1, unit_price=200000)
        medicine = Medicine.objects.create(name="Paracetamol", strength="500mg", unit="viên")
        supply = Supply.objects.create(name="Găng tay nitrile", unit="hộp", minimum_quantity=5)
        SupplyLot.objects.create(
            supply=supply,
            lot_number="GT-001",
            received_date=date(2026, 5, 13),
            expiry_date=date(2027, 5, 13),
            initial_quantity=20,
            unit_cost=100000,
        )
        prescription = Prescription.objects.create(
            patient=patient,
            appointment=doctor_schedule.appointments.first(),
            doctor=doctor,
            prescribed_at=date(2026, 5, 4),
        )
        PrescriptionItem.objects.create(
            prescription=prescription,
            medicine=medicine,
            dosage="1 viên/lần",
            quantity=10,
            instructions="Uống sau ăn.",
        )
        urls = [
            reverse("clinic:patient-list"),
            reverse("clinic:patient-detail", kwargs={"pk": patient.pk}),
            reverse("clinic:staff-list"),
            reverse("clinic:staff-detail", kwargs={"pk": doctor.pk}),
            reverse("clinic:service-category-list"),
            reverse("clinic:service-category-detail", kwargs={"pk": category.pk}),
            reverse("clinic:service-list"),
            reverse("clinic:service-detail", kwargs={"pk": service.pk}),
            reverse("clinic:price-list-list"),
            reverse("clinic:price-list-detail", kwargs={"pk": price_list.pk}),
            reverse("clinic:invoice-list"),
            reverse("clinic:invoice-detail", kwargs={"pk": invoice.pk}),
            reverse("clinic:medicine-list"),
            reverse("clinic:medicine-detail", kwargs={"pk": medicine.pk}),
            reverse("clinic:prescription-list"),
            reverse("clinic:prescription-detail", kwargs={"pk": prescription.pk}),
            reverse("clinic:supply-list"),
            reverse("clinic:supply-detail", kwargs={"pk": supply.pk}),
            reverse("clinic:holiday-list"),
            reverse("clinic:work-shift-list"),
            reverse("clinic:doctor-schedule-list"),
            reverse("clinic:appointment-calendar"),
            reverse("clinic:appointment-list"),
        ]

        for url in urls:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)

    def test_doctor_role_is_scoped_to_own_clinical_data(self):
        sync_role_groups()
        doctor_user = User.objects.create_user(
            username="doctor-user",
            password="StrongPass123!",
            is_staff=True,
        )
        doctor_user.groups.set([Group.objects.get(name=ROLE_DOCTOR)])
        doctor = make_staff(name="Bac Si Dang Nhap", role=Staff.Role.DOCTOR, user=doctor_user)
        other_doctor = make_staff(name="Bac Si Khac", role=Staff.Role.DOCTOR)
        own_patient = make_patient(name="Benh Nhan Cua Toi")
        other_patient = make_patient(name="Benh Nhan Khac")
        shift = make_shift(weekday=WorkShift.Weekday.MONDAY)
        own_schedule = make_schedule(doctor=doctor, work_date=date(2026, 5, 4), shift=shift)
        other_schedule = make_schedule(doctor=other_doctor, work_date=date(2026, 5, 4), shift=shift)
        own_appointment = make_appointment(
            patient=own_patient,
            doctor_schedule=own_schedule,
            start_time=time(8, 0),
            end_time=time(8, 30),
        )
        other_appointment = make_appointment(
            patient=other_patient,
            doctor_schedule=other_schedule,
            start_time=time(9, 0),
            end_time=time(9, 30),
        )
        own_prescription = make_prescription(patient=own_patient, doctor=doctor)
        other_prescription = make_prescription(patient=other_patient, doctor=other_doctor)

        self.client.logout()
        self.client.login(username="doctor-user", password="StrongPass123!")

        response = self.client.get(reverse("clinic:patient-list"))
        self.assertContains(response, own_patient.full_name)
        self.assertNotContains(response, other_patient.full_name)

        response = self.client.get(reverse("clinic:appointment-list"))
        self.assertContains(response, own_appointment.appointment_code)
        self.assertNotContains(response, other_appointment.appointment_code)

        response = self.client.get(reverse("clinic:prescription-list"))
        self.assertContains(response, own_prescription.prescription_code)
        self.assertNotContains(response, other_prescription.prescription_code)

        response = self.client.get(reverse("clinic:appointment-detail", kwargs={"pk": other_appointment.pk}))
        self.assertEqual(response.status_code, 404)

    def test_doctor_role_cannot_access_support_payroll_or_medicine_admin(self):
        sync_role_groups()
        doctor_user = User.objects.create_user(
            username="doctor-limited",
            password="StrongPass123!",
            is_staff=True,
        )
        doctor_user.groups.set([Group.objects.get(name=ROLE_DOCTOR)])
        make_staff(name="Bac Si Gioi Han", role=Staff.Role.DOCTOR, user=doctor_user)
        medicine = make_medicine()

        self.client.logout()
        self.client.login(username="doctor-limited", password="StrongPass123!")

        dashboard_response = self.client.get(reverse("clinic:dashboard"))
        self.assertEqual(dashboard_response.status_code, 200)
        self.assertNotContains(dashboard_response, "Tính lương")
        self.assertNotContains(dashboard_response, "Tin nhắn hỗ trợ")
        self.assertNotContains(dashboard_response, "Doanh thu (VND)")

        forbidden_urls = [
            reverse("payroll:payslip-list"),
            reverse("payroll:payslip-generate"),
            reverse("clinic:conversation-list"),
            reverse("clinic:medicine-create"),
            reverse("clinic:medicine-update", kwargs={"pk": medicine.pk}),
            reverse("clinic:medicine-delete", kwargs={"pk": medicine.pk}),
        ]
        for url in forbidden_urls:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 403)

    def test_patient_list_filters_and_patient_update_delete(self):
        patient = make_patient(
            name="Nguyen Thi Loc",
            gender=Patient.Gender.FEMALE,
            phone="0901000001",
        )
        inactive_patient = make_patient(name="Tran Van Ngung", is_active=False)

        response = self.client.get(
            reverse("clinic:patient-list"),
            {"q": "0901000001", "gender": Patient.Gender.FEMALE, "status": "active"},
        )
        self.assertContains(response, patient.full_name)
        self.assertNotContains(response, inactive_patient.full_name)

        response = self.client.post(
            reverse("clinic:patient-update", kwargs={"pk": patient.pk}),
            {
                "patient_code": patient.patient_code,
                "full_name": "Nguyen Thi Da Sua",
                "date_of_birth": "",
                "gender": Patient.Gender.FEMALE,
                "national_id": "",
                "phone": "0901000002",
                "email": "",
                "address": "",
                "occupation": "",
                "emergency_contact_name": "",
                "emergency_contact_phone": "",
                "blood_type": "",
                "medical_history": "",
                "current_medications": "",
                "allergy_note": "",
                "note": "",
                "is_active": "on",
            },
            follow=True,
        )
        patient.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(patient.full_name, "Nguyen Thi Da Sua")

        response = self.client.post(reverse("clinic:patient-delete", kwargs={"pk": patient.pk}), follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Patient.objects.filter(pk=patient.pk).exists())

    def test_staff_list_filters_and_staff_update_delete(self):
        doctor = make_staff(name="Bac Si Loc", role=Staff.Role.DOCTOR, specialization="Implant")
        inactive_staff = make_staff(name="Nhan Vien Ngung", role=Staff.Role.RECEPTIONIST, is_active=False)

        response = self.client.get(
            reverse("clinic:staff-list"),
            {"q": "Implant", "role": Staff.Role.DOCTOR, "status": "active"},
        )
        self.assertContains(response, doctor.full_name)
        self.assertNotContains(response, inactive_staff.full_name)

        response = self.client.post(
            reverse("clinic:staff-update", kwargs={"pk": doctor.pk}),
            {
                "employee_code": doctor.employee_code,
                "role": Staff.Role.DOCTOR,
                "full_name": "Bac Si Da Sua",
                "date_of_birth": "",
                "gender": Staff.Gender.MALE,
                "phone": "",
                "email": "",
                "address": "",
                "primary_workplace": "",
                "degree": "BS",
                "specialization": "Nha tong quat",
                "license_number": "",
                "experience_years": "",
                "start_date": "",
                "emergency_contact_name": "",
                "emergency_contact_phone": "",
                "note": "",
                "is_active": "on",
            },
            follow=True,
        )
        doctor.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(doctor.full_name, "Bac Si Da Sua")

        response = self.client.post(reverse("clinic:staff-delete", kwargs={"pk": doctor.pk}), follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Staff.objects.filter(pk=doctor.pk).exists())

    def test_service_list_shows_current_price(self):
        category = ServiceCategory.objects.create(name="Điều trị")
        service = Service.objects.create(category=category, name="Trám răng composite")
        price_list = PriceList.objects.create(name="Bảng giá hiện hành", effective_from=date(2026, 1, 1))
        ServicePrice.objects.create(price_list=price_list, service=service, price=500000)

        response = self.client.get(reverse("clinic:service-list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "500000")
        self.assertContains(response, "Bảng giá hiện hành")

    def test_service_list_can_filter_missing_current_price(self):
        category = ServiceCategory.objects.create(name="Phục hình")
        priced_service = Service.objects.create(category=category, name="Dịch vụ đã có giá")
        missing_price_service = Service.objects.create(category=category, name="Dịch vụ chưa có giá")
        price_list = PriceList.objects.create(name="Bảng giá hiện hành", effective_from=date(2026, 1, 1))
        ServicePrice.objects.create(price_list=price_list, service=priced_service, price=700000)

        response = self.client.get(reverse("clinic:service-list"), {"price_status": "missing"})

        self.assertContains(response, missing_price_service.name)
        self.assertNotContains(response, priced_service.name)

    def test_service_category_create_update_delete(self):
        response = self.client.post(
            reverse("clinic:service-category-create"),
            {
                "code": "",
                "name": "Nha khoa trẻ em",
                "description": "Dịch vụ cho trẻ em",
                "is_active": "on",
            },
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        category = ServiceCategory.objects.get(name="Nha khoa trẻ em")

        response = self.client.post(
            reverse("clinic:service-category-update", kwargs={"pk": category.pk}),
            {
                "code": category.code,
                "name": "Nha khoa trẻ em cập nhật",
                "description": "Đã cập nhật",
                "is_active": "on",
            },
            follow=True,
        )
        category.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(category.name, "Nha khoa trẻ em cập nhật")

        response = self.client.post(reverse("clinic:service-category-delete", kwargs={"pk": category.pk}), follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(ServiceCategory.objects.filter(pk=category.pk).exists())

    def test_can_create_service_from_management_view(self):
        category = ServiceCategory.objects.create(name="Thẩm mỹ nha khoa")

        response = self.client.post(
            reverse("clinic:service-create"),
            {
                "code": "",
                "category": category.pk,
                "name": "Tẩy trắng răng",
                "description": "Tẩy trắng răng tại phòng khám.",
                "duration_minutes": "60",
                "is_active": "on",
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(Service.objects.filter(name="Tẩy trắng răng").exists())

    def test_service_update_delete(self):
        category = ServiceCategory.objects.create(name="Dịch vụ cập nhật")
        service = Service.objects.create(category=category, name="Dịch vụ cũ")

        response = self.client.post(
            reverse("clinic:service-update", kwargs={"pk": service.pk}),
            {
                "code": service.code,
                "category": category.pk,
                "name": "Dịch vụ mới",
                "description": "Đã sửa",
                "duration_minutes": "45",
                "is_active": "on",
            },
            follow=True,
        )
        service.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(service.name, "Dịch vụ mới")
        self.assertEqual(service.duration_minutes, 45)

        response = self.client.post(reverse("clinic:service-delete", kwargs={"pk": service.pk}), follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Service.objects.filter(pk=service.pk).exists())

    def test_price_list_create_filter_update_delete(self):
        response = self.client.post(
            reverse("clinic:price-list-create"),
            {
                "name": "Bảng giá test",
                "effective_from": "2026-01-01",
                "effective_to": "",
                "is_active": "on",
                "note": "Giá hiện hành",
            },
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        price_list = PriceList.objects.get(name="Bảng giá test")

        response = self.client.get(reverse("clinic:price-list-list"), {"apply_status": "current"})
        self.assertContains(response, price_list.name)

        response = self.client.post(
            reverse("clinic:price-list-update", kwargs={"pk": price_list.pk}),
            {
                "name": "Bảng giá test cập nhật",
                "effective_from": "2026-01-01",
                "effective_to": "2026-12-31",
                "is_active": "on",
                "note": "Đã cập nhật",
            },
            follow=True,
        )
        price_list.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(price_list.name, "Bảng giá test cập nhật")

        response = self.client.post(reverse("clinic:price-list-delete", kwargs={"pk": price_list.pk}), follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(PriceList.objects.filter(pk=price_list.pk).exists())

    def test_can_create_staff_from_management_view(self):
        response = self.client.post(
            reverse("clinic:staff-create"),
            {
                "employee_code": "",
                "role": Staff.Role.DOCTOR,
                "full_name": "Tran Thi B",
                "date_of_birth": "1988-01-15",
                "gender": Staff.Gender.FEMALE,
                "phone": "0909000000",
                "email": "doctor@example.com",
                "address": "12 Nguyen Trai, TP.HCM",
                "primary_workplace": "Phòng khám trung tâm",
                "degree": "ThS.BS",
                "specialization": "Chỉnh nha",
                "license_number": "CCHN-012345",
                "experience_years": "8",
                "start_date": "2024-01-02",
                "emergency_contact_name": "Tran Van C",
                "emergency_contact_phone": "0909111222",
                "note": "Phụ trách ca chỉnh nha.",
                "is_active": "on",
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(Staff.objects.filter(full_name="Tran Thi B").exists())

    def test_can_create_staff_with_linked_login_account(self):
        response = self.client.post(
            reverse("clinic:staff-create"),
            {
                "employee_code": "",
                "role": Staff.Role.DOCTOR,
                "full_name": "Tran Thi Co Tai Khoan",
                "phone": "0909001111",
                "email": "linked-doctor@example.com",
                "is_active": "on",
                "create_login_account": "on",
                "username": "",
                "initial_password": "",
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        staff = Staff.objects.get(full_name="Tran Thi Co Tai Khoan")
        self.assertIsNotNone(staff.user)
        self.assertEqual(staff.user.username, staff.employee_code.lower())
        self.assertTrue(staff.user.is_staff)
        self.assertTrue(staff.user.is_active)
        self.assertTrue(staff.user.groups.filter(name=ROLE_DOCTOR).exists())
        self.assertTrue(get_user_security_profile(staff.user).must_change_password)
        self.assertContains(response, staff.user.username)
        self.assertContains(response, "Mật khẩu:")

    def test_updating_staff_role_resyncs_linked_user_group(self):
        user = User.objects.create_user(
            username="staff-role-sync",
            password="StrongPass123!",
            is_staff=True,
            is_active=True,
        )
        receptionist_group, _ = Group.objects.get_or_create(name="Lễ tân")
        user.groups.set([receptionist_group])
        staff = Staff.objects.create(
            employee_code="NV-ROLE-001",
            role=Staff.Role.RECEPTIONIST,
            full_name="Nhan Vien Doi Role",
            user=user,
        )

        response = self.client.post(
            reverse("clinic:staff-update", kwargs={"pk": staff.pk}),
            {
                "employee_code": staff.employee_code,
                "role": Staff.Role.ASSISTANT,
                "full_name": staff.full_name,
                "date_of_birth": "",
                "gender": "",
                "phone": "",
                "email": "",
                "address": "",
                "primary_workplace": "",
                "degree": "",
                "specialization": "",
                "license_number": "",
                "experience_years": "",
                "start_date": "",
                "emergency_contact_name": "",
                "emergency_contact_phone": "",
                "note": "",
                "is_active": "on",
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        staff.refresh_from_db()
        user.refresh_from_db()
        self.assertEqual(staff.role, Staff.Role.ASSISTANT)
        self.assertTrue(user.groups.filter(name=ROLE_ASSISTANT).exists())
        self.assertFalse(user.groups.filter(name="Lễ tân").exists())

    def test_deleting_staff_deactivates_linked_user(self):
        user = User.objects.create_user(
            username="staff-delete-user",
            password="StrongPass123!",
            is_staff=True,
            is_active=True,
        )
        staff = Staff.objects.create(
            employee_code="NV-DELETE-001",
            role=Staff.Role.RECEPTIONIST,
            full_name="Nhan Vien Xoa",
            user=user,
        )

        response = self.client.post(reverse("clinic:staff-delete", kwargs={"pk": staff.pk}), follow=True)

        self.assertEqual(response.status_code, 200)
        self.assertFalse(Staff.objects.filter(pk=staff.pk).exists())
        user.refresh_from_db()
        self.assertFalse(user.is_active)

    def test_can_create_patient_from_management_view(self):
        response = self.client.post(
            reverse("clinic:patient-create"),
            {
                "patient_code": "",
                "full_name": "Nguyen Thi Patient",
                "date_of_birth": "1995-03-20",
                "gender": Patient.Gender.FEMALE,
                "national_id": "079195000001",
                "phone": "0912345678",
                "email": "patient@example.com",
                "address": "45 Le Loi, TP.HCM",
                "occupation": "Nhan vien van phong",
                "emergency_contact_name": "Nguyen Van Than",
                "emergency_contact_phone": "0987654321",
                "blood_type": Patient.BloodType.O_POSITIVE,
                "medical_history": "Tăng huyết áp nhẹ",
                "current_medications": "Amlodipine 5mg",
                "allergy_note": "Dị ứng penicillin",
                "note": "Ưu tiên lịch buổi sáng.",
                "is_active": "on",
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(Patient.objects.filter(full_name="Nguyen Thi Patient").exists())

    def test_can_add_service_price_to_price_list(self):
        category = ServiceCategory.objects.create(name="Điều trị")
        service = Service.objects.create(category=category, name="Trám răng")
        price_list = PriceList.objects.create(name="Bảng giá 2026", effective_from=date(2026, 1, 1))

        response = self.client.post(
            reverse("clinic:service-price-create", kwargs={"price_list_pk": price_list.pk}),
            {
                "service": service.pk,
                "price": "500000",
                "note": "Giá tiêu chuẩn",
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(ServicePrice.objects.filter(price_list=price_list, service=service).exists())

    def test_service_price_update_delete(self):
        service = make_service(name="Điều trị tủy")
        price_list = make_price_list()
        service_price = ServicePrice.objects.create(price_list=price_list, service=service, price=900000)

        response = self.client.post(
            reverse("clinic:service-price-update", kwargs={"pk": service_price.pk}),
            {
                "price_list": price_list.pk,
                "service": service.pk,
                "price": "950000",
                "note": "Cập nhật",
            },
            follow=True,
        )
        service_price.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(service_price.price, 950000)

        response = self.client.post(reverse("clinic:service-price-delete", kwargs={"pk": service_price.pk}), follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(ServicePrice.objects.filter(pk=service_price.pk).exists())

    def test_invoice_create_auto_adds_appointment_service_price_and_pdf_renders(self):
        service = make_service(name="Cạo vôi răng")
        price_list = PriceList.objects.create(name="Bảng giá hiện hành", effective_from=date(2020, 1, 1))
        ServicePrice.objects.create(price_list=price_list, service=service, price=350000)
        appointment = make_appointment(service=service)

        response = self.client.post(
            reverse("clinic:invoice-create"),
            {
                "invoice_code": "",
                "patient": appointment.patient.pk,
                "appointment": appointment.pk,
                "issue_date": "2026-05-13",
                "due_date": "",
                "payment_type": Invoice.PaymentType.ONE_TIME,
                "note": "",
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        invoice = Invoice.objects.get(appointment=appointment)
        self.assertEqual(invoice.total_amount, Decimal("350000"))
        self.assertTrue(invoice.items.filter(service=service).exists())

        response = self.client.get(reverse("clinic:invoice-pdf", kwargs={"pk": invoice.pk}))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertTrue(response.content.startswith(b"%PDF"))

    def test_invoice_items_and_payments_update_invoice_status(self):
        invoice = make_invoice()

        response = self.client.post(
            reverse("clinic:invoice-item-create", kwargs={"invoice_pk": invoice.pk}),
            {
                "service": "",
                "description": "Điều trị nha chu",
                "quantity": "1",
                "unit_price": "450000",
                "note": "",
            },
            follow=True,
        )
        invoice.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(invoice.total_amount, Decimal("450000"))
        item = invoice.items.first()

        response = self.client.post(
            reverse("clinic:payment-create", kwargs={"invoice_pk": invoice.pk}),
            {
                "paid_at": "2026-05-13",
                "amount": "450000",
                "method": Payment.Method.TRANSFER,
                "note": "Thanh toán đủ",
            },
            follow=True,
        )
        invoice.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(invoice.status, Invoice.Status.PAID)

        response = self.client.post(reverse("clinic:invoice-item-delete", kwargs={"pk": item.pk}), follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(InvoiceItem.objects.filter(pk=item.pk).exists())

    @override_settings(
        MOMO_PARTNER_CODE="MOMO_TEST",
        MOMO_ACCESS_KEY="ACCESS123",
        MOMO_SECRET_KEY="SECRET123",
        MOMO_CREATE_ENDPOINT="https://example.com/create",
        MOMO_QUERY_ENDPOINT="https://example.com/query",
    )
    @patch("apps.clinic.views.create_momo_transaction")
    def test_can_create_momo_payment_transaction_from_invoice(self, mocked_create_transaction):
        invoice = make_invoice(patient=make_patient(email="receipt@example.com"))
        InvoiceItem.objects.create(invoice=invoice, description="Điều trị", quantity=1, unit_price=300000)

        mocked_create_transaction.return_value = {"resultCode": 0}

        response = self.client.post(
            reverse("clinic:momo-payment-create", kwargs={"invoice_pk": invoice.pk}),
            {
                "amount": "300000",
                "customer_email": "receipt@example.com",
            },
            follow=True,
        )

        payment_transaction = PaymentTransaction.objects.get(invoice=invoice)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payment_transaction.amount, Decimal("300000"))
        self.assertEqual(payment_transaction.customer_email, "receipt@example.com")
        mocked_create_transaction.assert_called_once()

    @override_settings(
        MOMO_PARTNER_CODE="MOMO_TEST",
        MOMO_ACCESS_KEY="ACCESS123",
        MOMO_SECRET_KEY="SECRET123",
        MOMO_CREATE_ENDPOINT="https://example.com/create",
        MOMO_QUERY_ENDPOINT="https://example.com/query",
    )
    def test_momo_ipn_creates_payment_for_successful_transaction(self):
        invoice = make_invoice()
        InvoiceItem.objects.create(invoice=invoice, description="Điều trị", quantity=1, unit_price=300000)
        payment_transaction = PaymentTransaction.objects.create(
            invoice=invoice,
            amount=Decimal("300000"),
            customer_email="receipt@example.com",
            order_id="INV_TEST_001",
            request_id="REQ_TEST_001",
        )
        payload = {
            "partnerCode": "MOMO_TEST",
            "orderId": payment_transaction.order_id,
            "requestId": payment_transaction.request_id,
            "amount": 300000,
            "orderInfo": f"Thanh toan hoa don {invoice.invoice_code}",
            "orderType": "momo_wallet",
            "transId": 99887766,
            "resultCode": 0,
            "message": "Successful.",
            "payType": "qr",
            "responseTime": 1721720663942,
            "extraData": "",
        }
        raw_signature = (
            "accessKey=ACCESS123&amount=300000&extraData=&message=Successful."
            f"&orderId={payment_transaction.order_id}&orderInfo=Thanh toan hoa don {invoice.invoice_code}"
            "&orderType=momo_wallet&partnerCode=MOMO_TEST&payType=qr"
            f"&requestId={payment_transaction.request_id}&responseTime=1721720663942&resultCode=0&transId=99887766"
        )
        payload["signature"] = make_momo_signature(raw_signature)

        response = self.client.post(
            reverse("clinic:momo-ipn"),
            data=json.dumps(payload),
            content_type="application/json",
        )

        payment_transaction.refresh_from_db()
        invoice.refresh_from_db()
        self.assertEqual(response.status_code, 204)
        self.assertEqual(payment_transaction.status, PaymentTransaction.Status.SUCCESS)
        self.assertTrue(Payment.objects.filter(invoice=invoice, method=Payment.Method.MOMO, amount=300000).exists())
        self.assertEqual(invoice.paid_amount, Decimal("300000"))

    @override_settings(
        MOMO_PARTNER_CODE="MOMO_TEST",
        MOMO_ACCESS_KEY="ACCESS123",
        MOMO_SECRET_KEY="SECRET123",
        MOMO_SIMULATE=True,
    )
    def test_momo_simulation_flow_success(self):
        invoice = make_invoice()
        InvoiceItem.objects.create(invoice=invoice, description="Điều trị", quantity=1, unit_price=300000)
        
        payment_transaction = PaymentTransaction.objects.create(
            invoice=invoice,
            amount=Decimal("300000"),
            customer_email="receipt@example.com",
            order_id="INV_TEST_SIM_001",
            request_id="REQ_TEST_SIM_001",
        )
        
        from django.test import RequestFactory
        factory = RequestFactory()
        request = factory.get('/')
        
        from .views import create_momo_transaction
        response_data = create_momo_transaction(payment_transaction, request)
        
        self.assertIn("payments/momo/simulate/", response_data["payUrl"])
        self.assertEqual(payment_transaction.pay_url, response_data["payUrl"])
        
        simulate_url = reverse("clinic:momo-simulate-payment", kwargs={"pk": payment_transaction.pk})
        response = self.client.get(simulate_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Cổng Thanh Toán MoMo (Giả Lập)")
        self.assertContains(response, "INV_TEST_SIM_001")
        
        post_response = self.client.post(simulate_url, {"action": "success"}, follow=True)
        self.assertEqual(post_response.status_code, 200)
        self.assertTemplateUsed(post_response, "clinic/momo_return.html")
        
        payment_transaction.refresh_from_db()
        invoice.refresh_from_db()
        self.assertEqual(payment_transaction.status, PaymentTransaction.Status.SUCCESS)
        self.assertTrue(Payment.objects.filter(invoice=invoice, method=Payment.Method.MOMO, amount=300000).exists())
        self.assertEqual(invoice.paid_amount, Decimal("300000"))

    @override_settings(
        MOMO_PARTNER_CODE="MOMO_TEST",
        MOMO_ACCESS_KEY="ACCESS123",
        MOMO_SECRET_KEY="SECRET123",
        MOMO_SIMULATE=True,
    )
    def test_momo_simulation_flow_failure(self):
        invoice = make_invoice()
        InvoiceItem.objects.create(invoice=invoice, description="Điều trị", quantity=1, unit_price=300000)
        
        payment_transaction = PaymentTransaction.objects.create(
            invoice=invoice,
            amount=Decimal("300000"),
            customer_email="receipt@example.com",
            order_id="INV_TEST_SIM_002",
            request_id="REQ_TEST_SIM_002",
        )
        
        simulate_url = reverse("clinic:momo-simulate-payment", kwargs={"pk": payment_transaction.pk})
        
        post_response = self.client.post(simulate_url, {"action": "fail"}, follow=True)
        self.assertEqual(post_response.status_code, 200)
        self.assertTemplateUsed(post_response, "clinic/momo_return.html")
        
        payment_transaction.refresh_from_db()
        invoice.refresh_from_db()
        self.assertEqual(payment_transaction.status, PaymentTransaction.Status.FAILED)
        self.assertFalse(Payment.objects.filter(invoice=invoice, method=Payment.Method.MOMO).exists())

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_send_invoice_receipt_email_attaches_invoice_pdf(self):
        invoice = make_invoice(patient=make_patient(email="receipt@example.com"))
        InvoiceItem.objects.create(invoice=invoice, description="Điều trị", quantity=1, unit_price=200000)
        payment_obj = Payment.objects.create(
            invoice=invoice,
            amount=Decimal("200000"),
            method=Payment.Method.MOMO,
        )
        payment_transaction = PaymentTransaction.objects.create(
            invoice=invoice,
            payment=payment_obj,
            amount=Decimal("200000"),
            customer_email="receipt@example.com",
            order_id="INV_TEST_002",
            request_id="REQ_TEST_002",
            status=PaymentTransaction.Status.SUCCESS,
            trans_id="123456789",
        )

        send_invoice_receipt_email(payment_transaction.pk)
        payment_transaction.refresh_from_db()

        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["receipt@example.com"])
        self.assertEqual(mail.outbox[0].attachments[0][2], "application/pdf")
        self.assertIsNotNone(payment_transaction.receipt_email_sent_at)

    def test_medicine_and_prescription_crud(self):
        response = self.client.post(
            reverse("clinic:medicine-create"),
            {
                "medicine_code": "",
                "name": "Amoxicillin",
                "active_ingredient": "Amoxicillin",
                "strength": "500mg",
                "unit": "viên",
                "usage_note": "Uống sau ăn.",
                "is_active": "on",
            },
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        medicine = Medicine.objects.get(name="Amoxicillin")

        response = self.client.post(
            reverse("clinic:medicine-update", kwargs={"pk": medicine.pk}),
            {
                "medicine_code": medicine.medicine_code,
                "name": "Amoxicillin cập nhật",
                "active_ingredient": "Amoxicillin",
                "strength": "500mg",
                "unit": "viên",
                "usage_note": "Uống sau ăn.",
                "is_active": "on",
            },
            follow=True,
        )
        medicine.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(medicine.name, "Amoxicillin cập nhật")

        appointment = make_appointment()
        response = self.client.post(
            reverse("clinic:prescription-create"),
            {
                "prescription_code": "",
                "patient": appointment.patient.pk,
                "appointment": appointment.pk,
                "doctor": appointment.doctor.pk,
                "prescribed_at": "2026-05-13",
                "diagnosis": "Đau răng",
                "note": "",
            },
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        prescription = Prescription.objects.get(patient=appointment.patient)

        response = self.client.post(
            reverse("clinic:prescription-item-create", kwargs={"prescription_pk": prescription.pk}),
            {
                "medicine": medicine.pk,
                "dosage": "1 viên/lần, ngày 2 lần",
                "quantity": "10",
                "instructions": "Uống sau ăn sáng và tối.",
                "note": "",
            },
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        item = PrescriptionItem.objects.get(prescription=prescription, medicine=medicine)

        response = self.client.post(
            reverse("clinic:prescription-item-update", kwargs={"pk": item.pk}),
            {
                "prescription": prescription.pk,
                "medicine": medicine.pk,
                "dosage": "1 viên/lần",
                "quantity": "12",
                "instructions": "Uống sau ăn.",
                "note": "Đã cập nhật",
            },
            follow=True,
        )
        item.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(item.quantity, 12)

        response = self.client.post(reverse("clinic:prescription-item-delete", kwargs={"pk": item.pk}), follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(PrescriptionItem.objects.filter(pk=item.pk).exists())

    def test_supply_inventory_crud_and_stock_movements(self):
        response = self.client.post(
            reverse("clinic:supply-create"),
            {
                "supply_code": "",
                "name": "Composite A2",
                "category": Supply.Category.RESTORATIVE,
                "unit": "tuýp",
                "minimum_quantity": "5",
                "description": "Vật liệu trám răng.",
                "is_active": "on",
            },
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        supply = Supply.objects.get(name="Composite A2")

        response = self.client.post(
            reverse("clinic:supply-update", kwargs={"pk": supply.pk}),
            {
                "supply_code": supply.supply_code,
                "name": "Composite A2 cập nhật",
                "category": Supply.Category.RESTORATIVE,
                "unit": "tuýp",
                "minimum_quantity": "6",
                "description": "Đã cập nhật.",
                "is_active": "on",
            },
            follow=True,
        )
        supply.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(supply.name, "Composite A2 cập nhật")

        response = self.client.post(
            reverse("clinic:supply-lot-create", kwargs={"supply_pk": supply.pk}),
            {
                "lot_number": "COM-A2-001",
                "supplier": "Demo Dental",
                "received_date": "2026-05-13",
                "expiry_date": "2027-05-13",
                "initial_quantity": "12",
                "unit_cost": "320000",
                "note": "",
            },
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        lot = SupplyLot.objects.get(supply=supply, lot_number="COM-A2-001")
        self.assertEqual(lot.current_quantity, Decimal("12"))

        response = self.client.post(
            reverse("clinic:supply-export-create", kwargs={"supply_pk": supply.pk}),
            {
                "lot": lot.pk,
                "export_date": "2026-05-13",
                "quantity": "4",
                "used_for": "Ca trám răng",
                "performed_by": "",
                "note": "",
            },
            follow=True,
        )
        lot.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(lot.current_quantity, Decimal("8.00"))
        export = SupplyExport.objects.get(lot=lot)

        response = self.client.post(
            reverse("clinic:supply-export-update", kwargs={"pk": export.pk}),
            {
                "lot": lot.pk,
                "export_date": "2026-05-13",
                "quantity": "5",
                "used_for": "Ca trám răng cập nhật",
                "performed_by": "",
                "note": "Đã cập nhật",
            },
            follow=True,
        )
        lot.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(lot.current_quantity, Decimal("7.00"))

        response = self.client.post(reverse("clinic:supply-export-delete", kwargs={"pk": export.pk}), follow=True)
        lot.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(lot.current_quantity, Decimal("12.00"))

        response = self.client.post(reverse("clinic:supply-lot-delete", kwargs={"pk": lot.pk}), follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(SupplyLot.objects.filter(pk=lot.pk).exists())

        response = self.client.post(reverse("clinic:supply-delete", kwargs={"pk": supply.pk}), follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Supply.objects.filter(pk=supply.pk).exists())

    def test_holiday_work_shift_and_doctor_schedule_crud(self):
        response = self.client.post(
            reverse("clinic:holiday-create"),
            {
                "date": "2026-06-01",
                "name": "Nghỉ nội bộ",
                "note": "",
                "is_active": "on",
            },
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        holiday = ClinicHoliday.objects.get(date=date(2026, 6, 1))

        response = self.client.post(
            reverse("clinic:holiday-update", kwargs={"pk": holiday.pk}),
            {
                "date": "2026-06-01",
                "name": "Nghỉ nội bộ cập nhật",
                "note": "Đã sửa",
                "is_active": "on",
            },
            follow=True,
        )
        holiday.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(holiday.name, "Nghỉ nội bộ cập nhật")

        response = self.client.post(
            reverse("clinic:work-shift-create"),
            {
                "name": "Ca test CRUD",
                "weekday": WorkShift.Weekday.THURSDAY,
                "start_time": "08:00",
                "end_time": "12:00",
                "is_active": "on",
                "note": "",
            },
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        shift = WorkShift.objects.get(name="Ca test CRUD")
        doctor = make_staff(name="Bac si CRUD", role=Staff.Role.DOCTOR)

        response = self.client.post(
            reverse("clinic:doctor-schedule-create"),
            {
                "doctor": doctor.pk,
                "work_date": "2026-05-14",
                "shift": shift.pk,
                "status": DoctorSchedule.Status.REGISTERED,
                "note": "",
            },
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        schedule = DoctorSchedule.objects.get(doctor=doctor, work_date=date(2026, 5, 14), shift=shift)

        response = self.client.post(
            reverse("clinic:doctor-schedule-update", kwargs={"pk": schedule.pk}),
            {
                "doctor": doctor.pk,
                "work_date": "2026-05-14",
                "shift": shift.pk,
                "status": DoctorSchedule.Status.COMPLETED,
                "note": "Đã hoàn tất",
            },
            follow=True,
        )
        schedule.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(schedule.status, DoctorSchedule.Status.COMPLETED)

        response = self.client.post(reverse("clinic:doctor-schedule-delete", kwargs={"pk": schedule.pk}), follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(DoctorSchedule.objects.filter(pk=schedule.pk).exists())

        response = self.client.post(reverse("clinic:work-shift-delete", kwargs={"pk": shift.pk}), follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(WorkShift.objects.filter(pk=shift.pk).exists())

        response = self.client.post(reverse("clinic:holiday-delete", kwargs={"pk": holiday.pk}), follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(ClinicHoliday.objects.filter(pk=holiday.pk).exists())

    def test_can_create_appointment_from_management_view(self):
        doctor = Staff.objects.create(full_name="Do Van Doctor", role=Staff.Role.DOCTOR)
        patient = Patient.objects.create(full_name="Vo Thi Patient")
        shift = WorkShift.objects.create(
            name="Ca sáng",
            weekday=WorkShift.Weekday.MONDAY,
            start_time=time(8, 0),
            end_time=time(12, 0),
        )
        doctor_schedule = DoctorSchedule.objects.create(
            doctor=doctor,
            work_date=date(2026, 5, 4),
            shift=shift,
        )

        response = self.client.post(
            reverse("clinic:appointment-create"),
            {
                "appointment_code": "",
                "patient": patient.pk,
                "doctor_schedule": doctor_schedule.pk,
                "service": "",
                "start_time": "09:00",
                "end_time": "09:30",
                "arrival_type": Appointment.ArrivalType.SCHEDULED,
                "visit_type": Appointment.VisitType.NEW,
                "priority_level": Appointment.PriorityLevel.NORMAL,
                "status": Appointment.Status.SCHEDULED,
                "chief_complaint": "Đau răng",
                "note": "",
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(Appointment.objects.filter(patient=patient, doctor_schedule=doctor_schedule).exists())

    def test_appointment_update_delete(self):
        appointment = make_appointment(chief_complaint="Đau răng")

        response = self.client.post(
            reverse("clinic:appointment-update", kwargs={"pk": appointment.pk}),
            {
                "appointment_code": appointment.appointment_code,
                "patient": appointment.patient.pk,
                "doctor_schedule": appointment.doctor_schedule.pk,
                "service": "",
                "start_time": "09:30",
                "end_time": "10:00",
                "arrival_type": appointment.arrival_type,
                "visit_type": Appointment.VisitType.FOLLOW_UP,
                "priority_level": Appointment.PriorityLevel.PRIORITY,
                "status": Appointment.Status.CONFIRMED,
                "chief_complaint": "Đau răng cập nhật",
                "note": "Đã xác nhận",
            },
            follow=True,
        )
        appointment.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(appointment.status, Appointment.Status.CONFIRMED)
        self.assertEqual(appointment.visit_type, Appointment.VisitType.FOLLOW_UP)
        self.assertEqual(appointment.priority_level, Appointment.PriorityLevel.PRIORITY)
        self.assertEqual(appointment.chief_complaint, "Đau răng cập nhật")

        response = self.client.post(reverse("clinic:appointment-delete", kwargs={"pk": appointment.pk}), follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Appointment.objects.filter(pk=appointment.pk).exists())

    def test_appointment_calendar_renders_week_and_filters(self):
        doctor = make_staff(name="Bac si lich A", role=Staff.Role.DOCTOR)
        other_doctor = make_staff(name="Bac si lich B", role=Staff.Role.DOCTOR)
        shift = make_shift(
            weekday=WorkShift.Weekday.WEDNESDAY,
            start_time=time(8, 0),
            end_time=time(12, 0),
        )
        schedule = make_schedule(doctor=doctor, work_date=date(2026, 5, 13), shift=shift)
        other_schedule = make_schedule(
            doctor=other_doctor,
            work_date=date(2026, 5, 13),
            shift=shift,
        )
        appointment = make_appointment(
            patient=make_patient(name="Benh nhan lich A"),
            doctor_schedule=schedule,
            start_time=time(9, 0),
            end_time=time(9, 30),
            status=Appointment.Status.CONFIRMED,
            chief_complaint="Kiểm tra lịch",
        )
        other_appointment = make_appointment(
            patient=make_patient(name="Benh nhan lich B"),
            doctor_schedule=other_schedule,
            start_time=time(10, 0),
            end_time=time(10, 30),
        )

        response = self.client.get(
            reverse("clinic:appointment-calendar"),
            {"date": "2026-05-13", "doctor": str(doctor.pk)},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "11/05/2026 - 17/05/2026")
        self.assertContains(response, appointment.patient.full_name)
        self.assertContains(response, "Đã xác nhận: 1")
        self.assertContains(response, "date=2026-05-13")
        self.assertContains(response, "start_time=09%3A30")
        self.assertContains(response, f"doctor={doctor.pk}")
        self.assertNotContains(response, other_appointment.patient.full_name)

        response = self.client.get(
            reverse("clinic:appointment-calendar"),
            {"date": "2026-05-13", "doctor": str(doctor.pk), "status": Appointment.Status.NO_SHOW},
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, appointment.patient.full_name)

    def test_reception_today_view_renders_and_filters_today_appointments(self):
        today = timezone.localdate()
        doctor = make_staff(name="Bac si tiep don", role=Staff.Role.DOCTOR)
        other_doctor = make_staff(name="Bac si khac", role=Staff.Role.DOCTOR)
        morning_shift = make_shift(
            name="Ca sáng tiếp đón",
            weekday=today.weekday(),
            start_time=time(8, 0),
            end_time=time(12, 0),
        )
        afternoon_shift = make_shift(
            name="Ca chiều tiếp đón",
            weekday=today.weekday(),
            start_time=time(13, 0),
            end_time=time(17, 0),
        )
        target_schedule = make_schedule(doctor=doctor, work_date=today, shift=morning_shift)
        other_schedule = make_schedule(doctor=other_doctor, work_date=today, shift=afternoon_shift)
        matching_patient = make_patient(name="Benh nhan dung bo loc", phone="0909000001")
        hidden_patient = make_patient(name="Benh nhan an")
        make_appointment(
            patient=matching_patient,
            doctor_schedule=target_schedule,
            chief_complaint="Đau răng",
            status=Appointment.Status.SCHEDULED,
        )
        make_appointment(
            patient=hidden_patient,
            doctor_schedule=other_schedule,
            chief_complaint="Cạo vôi",
            status=Appointment.Status.COMPLETED,
        )

        response = self.client.get(
            reverse("clinic:reception-today"),
            {
                "doctor": str(doctor.pk),
                "shift": str(morning_shift.pk),
                "status": Appointment.Status.SCHEDULED,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Tiếp đón hôm nay")
        self.assertContains(response, matching_patient.full_name)
        self.assertEqual(
            [appointment.patient.full_name for appointment in response.context["appointments"]],
            [matching_patient.full_name],
        )
        self.assertContains(response, "Tiếp nhận không hẹn trước")
        self.assertContains(response, "Tất cả loại lượt khám")
        self.assertContains(response, "Tất cả mức ưu tiên")

    def test_appointment_check_in_marks_patient_waiting_and_assigns_queue_number(self):
        today = timezone.localdate()
        doctor = make_staff(name="Bac si hang cho", role=Staff.Role.DOCTOR)
        shift = make_shift(
            name="Ca check-in",
            weekday=today.weekday(),
            start_time=time(8, 0),
            end_time=time(12, 0),
        )
        schedule = make_schedule(doctor=doctor, work_date=today, shift=shift)
        appointment = make_appointment(
            patient=make_patient(name="Benh nhan check-in"),
            doctor_schedule=schedule,
            status=Appointment.Status.SCHEDULED,
        )

        response = self.client.post(
            reverse("clinic:appointment-check-in", kwargs={"pk": appointment.pk}),
            {"next": reverse("clinic:reception-today")},
            follow=True,
        )

        appointment.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(appointment.status, Appointment.Status.CHECKED_IN)
        self.assertEqual(appointment.queue_number, 1)
        self.assertIsNotNone(appointment.checked_in_at)
        self.assertEqual(appointment.checked_in_by, self.user)

    def test_reception_walk_in_create_builds_checked_in_appointment_for_existing_patient(self):
        today = timezone.localdate()
        doctor = make_staff(name="Bac si walk-in", role=Staff.Role.DOCTOR)
        shift = make_shift(
            name="Ca walk-in",
            weekday=today.weekday(),
            start_time=time(8, 0),
            end_time=time(18, 0),
        )
        schedule = make_schedule(doctor=doctor, work_date=today, shift=shift)
        patient = make_patient(name="Benh nhan cu", phone="0911222333")

        mocked_now = timezone.make_aware(datetime.combine(today, time(9, 0)))
        with patch("apps.clinic.views.timezone.localtime", return_value=mocked_now):
            response = self.client.post(
                reverse("clinic:reception-walk-in-create"),
                {
                    "patient": patient.pk,
                    "new_full_name": "",
                    "new_phone": "",
                    "new_gender": "",
                    "new_date_of_birth": "",
                    "doctor_schedule": schedule.pk,
                    "service": "",
                    "visit_type": Appointment.VisitType.EMERGENCY,
                    "priority_level": Appointment.PriorityLevel.URGENT,
                    "chief_complaint": "Ê buốt răng",
                    "note": "Đến sớm hơn dự kiến",
                },
                follow=True,
            )

        appointment = Appointment.objects.get(patient=patient, arrival_type=Appointment.ArrivalType.WALK_IN)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(appointment.status, Appointment.Status.CHECKED_IN)
        self.assertEqual(appointment.queue_number, 1)
        self.assertEqual(appointment.checked_in_by, self.user)
        self.assertEqual(appointment.visit_type, Appointment.VisitType.EMERGENCY)
        self.assertEqual(appointment.priority_level, Appointment.PriorityLevel.URGENT)
        self.assertEqual(appointment.chief_complaint, "Ê buốt răng")

    def test_reception_walk_in_create_can_quick_create_new_patient(self):
        today = timezone.localdate()
        doctor = make_staff(name="Bac si tao moi", role=Staff.Role.DOCTOR)
        shift = make_shift(
            name="Ca tao moi",
            weekday=today.weekday(),
            start_time=time(8, 0),
            end_time=time(18, 0),
        )
        schedule = make_schedule(doctor=doctor, work_date=today, shift=shift)

        mocked_now = timezone.make_aware(datetime.combine(today, time(9, 0)))
        with patch("apps.clinic.views.timezone.localtime", return_value=mocked_now):
            response = self.client.post(
                reverse("clinic:reception-walk-in-create"),
                {
                    "patient": "",
                    "new_full_name": "Benh nhan moi tai quay",
                    "new_phone": "0933444555",
                    "new_gender": Patient.Gender.FEMALE,
                    "new_date_of_birth": "1998-04-20",
                    "doctor_schedule": schedule.pk,
                    "service": "",
                    "visit_type": Appointment.VisitType.NEW,
                    "priority_level": Appointment.PriorityLevel.NORMAL,
                    "chief_complaint": "Tư vấn implant",
                    "note": "",
                },
                follow=True,
            )

        patient = Patient.objects.get(full_name="Benh nhan moi tai quay")
        appointment = Appointment.objects.get(patient=patient, arrival_type=Appointment.ArrivalType.WALK_IN)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(patient.phone, "0933444555")
        self.assertEqual(appointment.status, Appointment.Status.CHECKED_IN)
        self.assertEqual(appointment.checked_in_by, self.user)

    def test_reception_waiting_queue_orders_urgent_before_normal(self):
        today = timezone.localdate()
        doctor = make_staff(name="Bac si uu tien", role=Staff.Role.DOCTOR)
        shift = make_shift(
            name="Ca hang cho uu tien",
            weekday=today.weekday(),
            start_time=time(8, 0),
            end_time=time(18, 0),
        )
        schedule = make_schedule(doctor=doctor, work_date=today, shift=shift)
        make_appointment(
            patient=make_patient(name="Benh nhan thuong"),
            doctor_schedule=schedule,
            status=Appointment.Status.CHECKED_IN,
            queue_number=1,
            checked_in_at=timezone.now(),
            checked_in_by=self.user,
            priority_level=Appointment.PriorityLevel.NORMAL,
        )
        make_appointment(
            patient=make_patient(name="Benh nhan khan"),
            doctor_schedule=schedule,
            status=Appointment.Status.CHECKED_IN,
            queue_number=2,
            checked_in_at=timezone.now(),
            checked_in_by=self.user,
            priority_level=Appointment.PriorityLevel.URGENT,
        )

        response = self.client.get(reverse("clinic:reception-today"))
        content = response.content.decode("utf-8")

        self.assertEqual(response.status_code, 200)
        self.assertLess(content.index("Benh nhan khan"), content.index("Benh nhan thuong"))

    def test_appointment_ticket_pdf_renders(self):
        today = timezone.localdate()
        doctor = make_staff(name="Bac si in phieu", role=Staff.Role.DOCTOR)
        shift = make_shift(
            name="Ca in phieu",
            weekday=today.weekday(),
            start_time=time(8, 0),
            end_time=time(12, 0),
        )
        schedule = make_schedule(doctor=doctor, work_date=today, shift=shift)
        appointment = make_appointment(
            patient=make_patient(name="Benh nhan in phieu"),
            doctor_schedule=schedule,
            status=Appointment.Status.CHECKED_IN,
            queue_number=5,
            checked_in_at=timezone.now(),
            checked_in_by=self.user,
            visit_type=Appointment.VisitType.FOLLOW_UP,
            priority_level=Appointment.PriorityLevel.PRIORITY,
        )

        response = self.client.get(reverse("clinic:appointment-ticket", kwargs={"pk": appointment.pk}))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertTrue(response.content.startswith(b"%PDF"))
