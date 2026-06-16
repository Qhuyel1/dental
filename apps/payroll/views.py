import calendar
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from django.contrib import messages
from django.db import transaction
from django.db.models import Sum
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.views.generic import (
    CreateView, DeleteView, DetailView, FormView,
    ListView, TemplateView, UpdateView, View,
)

from apps.clinic.models import Appointment, DoctorSchedule, Staff
from core.mixins import StaffRequiredMixin

from .forms import (
    AppointmentComplexityForm,
    PaySlipGenerateForm,
    PaySlipStatusForm,
    SalaryConfigForm,
)
from .models import AppointmentComplexity, PaySlip, PaySlipEntry, SalaryConfig


# ─── UC4.1 Cấu hình lương cơ bản ────────────────────────────────────────────

class SalaryConfigListView(StaffRequiredMixin, ListView):
    model = SalaryConfig
    template_name = "payroll/salary_config_list.html"
    context_object_name = "configs"
    permission_required = "users.view_payroll"

    def get_queryset(self):
        return SalaryConfig.objects.order_by("-effective_from")


class SalaryConfigCreateView(StaffRequiredMixin, CreateView):
    model = SalaryConfig
    form_class = SalaryConfigForm
    template_name = "payroll/salary_config_form.html"
    success_url = reverse_lazy("payroll:salary-config-list")
    permission_required = "users.manage_payroll"

    def form_valid(self, form):
        messages.success(self.request, "Đã thêm cấu hình lương cơ bản mới.")
        return super().form_valid(form)


class SalaryConfigUpdateView(StaffRequiredMixin, UpdateView):
    model = SalaryConfig
    form_class = SalaryConfigForm
    template_name = "payroll/salary_config_form.html"
    success_url = reverse_lazy("payroll:salary-config-list")
    permission_required = "users.manage_payroll"

    def form_valid(self, form):
        messages.success(self.request, "Đã cập nhật cấu hình lương cơ bản.")
        return super().form_valid(form)


class SalaryConfigDeleteView(StaffRequiredMixin, DeleteView):
    model = SalaryConfig
    template_name = "payroll/salary_config_confirm_delete.html"
    success_url = reverse_lazy("payroll:salary-config-list")
    permission_required = "users.manage_payroll"

    def form_valid(self, form):
        messages.success(self.request, "Đã xóa cấu hình lương.")
        return super().form_valid(form)


# ─── UC4.3 Hệ số ca phức tạp ─────────────────────────────────────────────────

class AppointmentComplexityCreateView(StaffRequiredMixin, CreateView):
    model = AppointmentComplexity
    form_class = AppointmentComplexityForm
    template_name = "payroll/complexity_form.html"
    permission_required = "users.manage_payroll"

    def dispatch(self, request, *args, **kwargs):
        self.appointment = get_object_or_404(
            Appointment.objects.select_related(
                "patient", "doctor_schedule__doctor", "doctor_schedule__shift"
            ),
            pk=kwargs["appointment_pk"],
        )
        if hasattr(self.appointment, "complexity"):
            return redirect(
                reverse("payroll:complexity-update", kwargs={"appointment_pk": self.appointment.pk})
            )
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["appointment"] = self.appointment
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["appointment"] = self.appointment
        return context

    def form_valid(self, form):
        form.instance.appointment = self.appointment
        form.instance.recorded_by = self.request.user
        messages.success(self.request, "Đã ghi nhận hệ số phức tạp cho lượt khám.")
        return super().form_valid(form)

    def get_success_url(self):
        return reverse(
            "clinic:appointment-detail",
            kwargs={"pk": self.appointment.pk},
        )


class AppointmentComplexityUpdateView(StaffRequiredMixin, UpdateView):
    model = AppointmentComplexity
    form_class = AppointmentComplexityForm
    template_name = "payroll/complexity_form.html"
    permission_required = "users.manage_payroll"

    def dispatch(self, request, *args, **kwargs):
        self.appointment = get_object_or_404(
            Appointment.objects.select_related(
                "patient", "doctor_schedule__doctor", "doctor_schedule__shift"
            ),
            pk=kwargs["appointment_pk"],
        )
        return super().dispatch(request, *args, **kwargs)

    def get_object(self, queryset=None):
        return get_object_or_404(AppointmentComplexity, appointment=self.appointment)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["appointment"] = self.appointment
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["appointment"] = self.appointment
        return context

    def form_valid(self, form):
        form.instance.recorded_by = self.request.user
        messages.success(self.request, "Đã cập nhật hệ số phức tạp.")
        return super().form_valid(form)

    def get_success_url(self):
        return reverse(
            "clinic:appointment-detail",
            kwargs={"pk": self.appointment.pk},
        )


class AppointmentComplexityDeleteView(StaffRequiredMixin, View):
    permission_required = "users.manage_payroll"

    def post(self, request, appointment_pk):
        appointment = get_object_or_404(Appointment, pk=appointment_pk)
        AppointmentComplexity.objects.filter(appointment=appointment).delete()
        messages.success(request, "Đã xóa hệ số phức tạp.")
        return redirect(reverse("clinic:appointment-detail", kwargs={"pk": appointment.pk}))


# ─── UC4.4 Phiếu lương ───────────────────────────────────────────────────────

def _compute_shift_hours(shift):
    """Số giờ thực tế của một ca (Decimal)."""
    start = shift.start_time
    end = shift.end_time
    minutes = (end.hour * 60 + end.minute) - (start.hour * 60 + start.minute)
    return Decimal(str(minutes)) / Decimal("60")


def _compute_patient_coefficient(schedule):
    """Tổng hệ số bệnh nhân phức tạp cho một DoctorSchedule."""
    total = (
        AppointmentComplexity.objects.filter(
            appointment__doctor_schedule=schedule,
        )
        .exclude(appointment__status=Appointment.Status.CANCELLED)
        .aggregate(total=Sum("complexity_coefficient"))["total"]
        or Decimal("0")
    )
    return total


def generate_payslip(doctor, month, year, note="", created_by=None):
    """
    Tạo PaySlip + tất cả PaySlipEntry cho doctor trong tháng/năm.
    Trả về (payslip, list_of_entries, error_message).
    """
    # Lấy cấu hình lương hiệu lực cho cuối tháng
    _, last_day_num = calendar.monthrange(year, month)
    last_day = date(year, month, last_day_num)
    salary_config = SalaryConfig.get_active_for_date(last_day)
    if not salary_config:
        return None, [], "Chưa có cấu hình lương cơ bản. Vui lòng thiết lập trước."

    schedules = (
        DoctorSchedule.objects.select_related("shift")
        .filter(
            doctor=doctor,
            work_date__year=year,
            work_date__month=month,
        )
        .exclude(status=DoctorSchedule.Status.CANCELLED)
        .order_by("work_date", "shift__start_time")
    )
    if not schedules.exists():
        return None, [], (
            f"Bác sĩ {doctor.full_name} không có ca trực nào trong tháng "
            f"{month:02d}/{year} (không tính ca đã hủy)."
        )

    with transaction.atomic():
        payslip = PaySlip(
            doctor=doctor,
            month=month,
            year=year,
            hourly_rate=salary_config.hourly_rate,
            doctor_coefficient=doctor.salary_coefficient,
            note=note,
            created_by=created_by,
        )
        payslip.save()

        entries = []
        for schedule in schedules:
            shift_hours = _compute_shift_hours(schedule.shift)
            shift_coeff = schedule.shift.shift_coefficient
            patient_coeff = _compute_patient_coefficient(schedule)

            entry = PaySlipEntry(
                payslip=payslip,
                doctor_schedule=schedule,
                shift_hours=shift_hours,
                shift_coefficient=shift_coeff,
                patient_coefficient_total=patient_coeff,
            )
            entry.compute()
            entries.append(entry)

        PaySlipEntry.objects.bulk_create(entries)
        payslip.recalculate()

    return payslip, entries, None


class PaySlipGenerateView(StaffRequiredMixin, FormView):
    form_class = PaySlipGenerateForm
    template_name = "payroll/payslip_generate_form.html"
    permission_required = "users.manage_payroll"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["payslips_recent"] = PaySlip.objects.select_related("doctor").order_by("-created_at")[:5]
        return context

    def form_valid(self, form):
        doctor = form.cleaned_data["doctor"]
        month = form.cleaned_data["month"]
        year = form.cleaned_data["year"]
        note = form.cleaned_data.get("note", "")

        payslip, _, error = generate_payslip(
            doctor=doctor,
            month=month,
            year=year,
            note=note,
            created_by=self.request.user,
        )
        if error:
            messages.error(self.request, error)
            return self.form_invalid(form)

        messages.success(
            self.request,
            f"Đã lập phiếu lương {payslip.payslip_code} cho bác sĩ {doctor.full_name}.",
        )
        return redirect(reverse("payroll:payslip-detail", kwargs={"pk": payslip.pk}))


class PaySlipListView(StaffRequiredMixin, ListView):
    model = PaySlip
    template_name = "payroll/payslip_list.html"
    context_object_name = "payslips"
    paginate_by = 30
    permission_required = "users.view_payroll"

    def get_queryset(self):
        qs = PaySlip.objects.select_related("doctor").order_by("-year", "-month", "doctor__full_name")
        doctor_id = self.request.GET.get("doctor", "").strip()
        year = self.request.GET.get("year", "").strip()
        month = self.request.GET.get("month", "").strip()
        status = self.request.GET.get("status", "").strip()
        if doctor_id.isdigit():
            qs = qs.filter(doctor_id=doctor_id)
        if year.isdigit():
            qs = qs.filter(year=int(year))
        if month.isdigit():
            qs = qs.filter(month=int(month))
        if status:
            qs = qs.filter(status=status)
        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["doctors"] = Staff.objects.filter(role=Staff.Role.DOCTOR, is_active=True).order_by("full_name")
        context["status_choices"] = PaySlip.Status.choices
        context["selected_doctor"] = self.request.GET.get("doctor", "")
        context["selected_year"] = self.request.GET.get("year", "")
        context["selected_month"] = self.request.GET.get("month", "")
        context["selected_status"] = self.request.GET.get("status", "")
        context["years"] = list(range(2020, timezone.localdate().year + 2))
        context["months"] = list(range(1, 13))
        return context


class PaySlipDetailView(StaffRequiredMixin, DetailView):
    model = PaySlip
    template_name = "payroll/payslip_detail.html"
    context_object_name = "payslip"
    permission_required = "users.view_payroll"

    def get_queryset(self):
        return PaySlip.objects.select_related("doctor", "created_by").prefetch_related(
            "entries__doctor_schedule__shift",
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["status_form"] = PaySlipStatusForm(instance=self.object)
        return context


class PaySlipUpdateStatusView(StaffRequiredMixin, View):
    permission_required = "users.manage_payroll"

    def post(self, request, pk):
        payslip = get_object_or_404(PaySlip, pk=pk)
        form = PaySlipStatusForm(request.POST, instance=payslip)
        if form.is_valid():
            form.save()
            messages.success(request, f"Đã cập nhật trạng thái phiếu lương {payslip.payslip_code}.")
        else:
            messages.error(request, "Dữ liệu không hợp lệ.")
        return redirect(reverse("payroll:payslip-detail", kwargs={"pk": pk}))


class PaySlipDeleteView(StaffRequiredMixin, DeleteView):
    model = PaySlip
    template_name = "payroll/payslip_confirm_delete.html"
    success_url = reverse_lazy("payroll:payslip-list")
    permission_required = "users.manage_payroll"

    def form_valid(self, form):
        if self.object.status == PaySlip.Status.PAID:
            messages.error(self.request, "Không thể xóa phiếu lương đã thanh toán.")
            return redirect(reverse("payroll:payslip-detail", kwargs={"pk": self.object.pk}))
        messages.success(self.request, f"Đã xóa phiếu lương {self.object.payslip_code}.")
        return super().form_valid(form)


# ─── UC4.5 Báo cáo tổng hợp tháng ───────────────────────────────────────────

class MonthlyPayrollReportView(StaffRequiredMixin, TemplateView):
    template_name = "payroll/report_monthly.html"
    permission_required = "users.view_payroll"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        today = timezone.localdate()
        month = int(self.request.GET.get("month", today.month))
        year = int(self.request.GET.get("year", today.year))
        month = max(1, min(12, month))
        year = max(2000, min(2100, year))

        payslips = (
            PaySlip.objects.select_related("doctor")
            .filter(month=month, year=year)
            .order_by("doctor__full_name")
        )
        total_amount = payslips.aggregate(total=Sum("total_amount"))["total"] or Decimal("0")
        total_hours = payslips.aggregate(total=Sum("total_converted_hours"))["total"] or Decimal("0")

        context.update({
            "payslips": payslips,
            "selected_month": month,
            "selected_year": year,
            "total_amount": total_amount,
            "total_converted_hours": total_hours,
            "years": list(range(2020, today.year + 2)),
            "months": list(range(1, 13)),
        })
        return context


# ─── UC4.6 Báo cáo 1 bác sĩ theo năm ────────────────────────────────────────

class DoctorAnnualReportView(StaffRequiredMixin, TemplateView):
    template_name = "payroll/report_doctor_annual.html"
    permission_required = "users.view_payroll"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        today = timezone.localdate()
        year = int(self.request.GET.get("year", today.year))
        year = max(2000, min(2100, year))
        doctor_id = self.request.GET.get("doctor", "")

        doctors = Staff.objects.filter(role=Staff.Role.DOCTOR, is_active=True).order_by("full_name")
        doctor = None
        monthly_data = []
        total_amount = Decimal("0")
        total_hours = Decimal("0")

        if doctor_id and doctor_id.isdigit():
            doctor = Staff.objects.filter(pk=doctor_id, role=Staff.Role.DOCTOR).first()

        if doctor:
            payslips_map = {
                p.month: p
                for p in PaySlip.objects.filter(doctor=doctor, year=year)
            }
            for m in range(1, 13):
                p = payslips_map.get(m)
                monthly_data.append({
                    "month": m,
                    "payslip": p,
                    "amount": p.total_amount if p else Decimal("0"),
                    "hours": p.total_converted_hours if p else Decimal("0"),
                })
            total_amount = sum(d["amount"] for d in monthly_data)
            total_hours = sum(d["hours"] for d in monthly_data)

        context.update({
            "doctors": doctors,
            "selected_doctor": doctor,
            "selected_year": year,
            "monthly_data": monthly_data,
            "total_amount": total_amount,
            "total_converted_hours": total_hours,
            "years": list(range(2020, today.year + 2)),
            "chart_labels": [f"T{m}" for m in range(1, 13)],
            "chart_values": [str(d["amount"]) for d in monthly_data],
        })
        return context


# ─── UC4.7 Báo cáo tất cả bác sĩ theo năm ───────────────────────────────────

class AnnualPayrollReportView(StaffRequiredMixin, TemplateView):
    template_name = "payroll/report_annual.html"
    permission_required = "users.view_payroll"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        today = timezone.localdate()
        year = int(self.request.GET.get("year", today.year))
        year = max(2000, min(2100, year))

        doctors = Staff.objects.filter(role=Staff.Role.DOCTOR, is_active=True).order_by("full_name")
        rows = []
        grand_total = Decimal("0")

        for doctor in doctors:
            payslips = PaySlip.objects.filter(doctor=doctor, year=year)
            total = payslips.aggregate(total=Sum("total_amount"))["total"] or Decimal("0")
            hours = payslips.aggregate(total=Sum("total_converted_hours"))["total"] or Decimal("0")
            monthly = {p.month: p.total_amount for p in payslips}
            rows.append({
                "doctor": doctor,
                "monthly": [monthly.get(m, Decimal("0")) for m in range(1, 13)],
                "total": total,
                "total_hours": hours,
                "payslip_count": payslips.count(),
            })
            grand_total += total

        context.update({
            "rows": rows,
            "selected_year": year,
            "grand_total": grand_total,
            "years": list(range(2020, today.year + 2)),
            "months": list(range(1, 13)),
        })
        return context
