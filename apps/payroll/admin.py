from django.contrib import admin

from .models import AppointmentComplexity, PaySlip, PaySlipEntry, SalaryConfig


@admin.register(SalaryConfig)
class SalaryConfigAdmin(admin.ModelAdmin):
    list_display = ["effective_from", "hourly_rate", "note"]
    ordering = ["-effective_from"]


@admin.register(AppointmentComplexity)
class AppointmentComplexityAdmin(admin.ModelAdmin):
    list_display = ["appointment", "complexity_coefficient", "note", "recorded_by"]
    search_fields = ["appointment__appointment_code"]


class PaySlipEntryInline(admin.TabularInline):
    model = PaySlipEntry
    extra = 0
    readonly_fields = ["converted_hours", "line_total"]


@admin.register(PaySlip)
class PaySlipAdmin(admin.ModelAdmin):
    list_display = [
        "payslip_code",
        "doctor",
        "month",
        "year",
        "total_converted_hours",
        "total_amount",
        "status",
    ]
    list_filter = ["status", "year", "month"]
    search_fields = ["payslip_code", "doctor__full_name"]
    readonly_fields = ["payslip_code", "total_converted_hours", "total_amount"]
    inlines = [PaySlipEntryInline]
