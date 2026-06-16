from django.urls import path

from .views import (
    AnnualPayrollReportView,
    AppointmentComplexityCreateView,
    AppointmentComplexityDeleteView,
    AppointmentComplexityUpdateView,
    DoctorAnnualReportView,
    MonthlyPayrollReportView,
    PaySlipDeleteView,
    PaySlipDetailView,
    PaySlipGenerateView,
    PaySlipListView,
    PaySlipUpdateStatusView,
    SalaryConfigCreateView,
    SalaryConfigDeleteView,
    SalaryConfigListView,
    SalaryConfigUpdateView,
)

app_name = "payroll"

urlpatterns = [
    # UC4.1 — Cấu hình lương cơ bản
    path("salary-configs/", SalaryConfigListView.as_view(), name="salary-config-list"),
    path("salary-configs/create/", SalaryConfigCreateView.as_view(), name="salary-config-create"),
    path("salary-configs/<int:pk>/edit/", SalaryConfigUpdateView.as_view(), name="salary-config-update"),
    path("salary-configs/<int:pk>/delete/", SalaryConfigDeleteView.as_view(), name="salary-config-delete"),
    # UC4.3 — Hệ số ca phức tạp (gắn vào Appointment)
    path(
        "appointments/<int:appointment_pk>/complexity/create/",
        AppointmentComplexityCreateView.as_view(),
        name="complexity-create",
    ),
    path(
        "appointments/<int:appointment_pk>/complexity/edit/",
        AppointmentComplexityUpdateView.as_view(),
        name="complexity-update",
    ),
    path(
        "appointments/<int:appointment_pk>/complexity/delete/",
        AppointmentComplexityDeleteView.as_view(),
        name="complexity-delete",
    ),
    # UC4.4 — Phiếu lương
    path("payslips/", PaySlipListView.as_view(), name="payslip-list"),
    path("payslips/generate/", PaySlipGenerateView.as_view(), name="payslip-generate"),
    path("payslips/<int:pk>/", PaySlipDetailView.as_view(), name="payslip-detail"),
    path("payslips/<int:pk>/status/", PaySlipUpdateStatusView.as_view(), name="payslip-update-status"),
    path("payslips/<int:pk>/delete/", PaySlipDeleteView.as_view(), name="payslip-delete"),
    # UC4.5 — Báo cáo lương tất cả bác sĩ trong 1 tháng
    path("reports/monthly/", MonthlyPayrollReportView.as_view(), name="report-monthly"),
    # UC4.6 — Báo cáo lương 1 bác sĩ trong 1 năm
    path("reports/doctor-annual/", DoctorAnnualReportView.as_view(), name="report-doctor-annual"),
    # UC4.7 — Báo cáo lương tất cả bác sĩ trong 1 năm
    path("reports/annual/", AnnualPayrollReportView.as_view(), name="report-annual"),
]
