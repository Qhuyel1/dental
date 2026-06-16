from django.contrib import admin

from .models import (
    Appointment,
    ClinicHoliday,
    DoctorSchedule,
    Invoice,
    InvoiceItem,
    Medicine,
    Patient,
    Payment,
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


@admin.register(Patient)
class PatientAdmin(admin.ModelAdmin):
    list_display = ("patient_code", "full_name", "user", "gender", "phone", "national_id", "blood_type", "is_active")
    list_filter = ("gender", "blood_type", "is_active")
    search_fields = (
        "patient_code",
        "full_name",
        "user__username",
        "national_id",
        "phone",
        "email",
        "emergency_contact_phone",
    )
    readonly_fields = ("created_at", "updated_at")


@admin.register(Staff)
class StaffAdmin(admin.ModelAdmin):
    list_display = ("employee_code", "full_name", "user", "role", "phone", "specialization", "license_number", "is_active")
    list_filter = ("role", "gender", "is_active")
    search_fields = (
        "employee_code",
        "full_name",
        "user__username",
        "phone",
        "email",
        "degree",
        "specialization",
        "license_number",
    )
    readonly_fields = ("created_at", "updated_at")


@admin.register(ServiceCategory)
class ServiceCategoryAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "is_active")
    list_filter = ("is_active",)
    search_fields = ("code", "name")
    readonly_fields = ("created_at", "updated_at")


@admin.register(Service)
class ServiceAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "category", "duration_minutes", "is_active")
    list_filter = ("category", "is_active")
    search_fields = ("code", "name", "category__name")
    readonly_fields = ("created_at", "updated_at")


class ServicePriceInline(admin.TabularInline):
    model = ServicePrice
    extra = 1
    autocomplete_fields = ("service",)


@admin.register(PriceList)
class PriceListAdmin(admin.ModelAdmin):
    list_display = ("name", "effective_from", "effective_to", "is_active")
    list_filter = ("is_active", "effective_from")
    search_fields = ("name",)
    readonly_fields = ("created_at", "updated_at")
    inlines = (ServicePriceInline,)


@admin.register(ServicePrice)
class ServicePriceAdmin(admin.ModelAdmin):
    list_display = ("price_list", "service", "price")
    list_filter = ("price_list", "service__category")
    search_fields = ("price_list__name", "service__code", "service__name")
    autocomplete_fields = ("price_list", "service")
    readonly_fields = ("created_at", "updated_at")


class InvoiceItemInline(admin.TabularInline):
    model = InvoiceItem
    extra = 1
    autocomplete_fields = ("service",)
    readonly_fields = ("line_total",)


class PaymentInline(admin.TabularInline):
    model = Payment
    extra = 0


@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = ("invoice_code", "patient", "issue_date", "payment_type", "total_amount", "paid_amount", "status")
    list_filter = ("status", "payment_type", "issue_date")
    search_fields = ("invoice_code", "patient__patient_code", "patient__full_name", "patient__phone")
    autocomplete_fields = ("patient", "appointment")
    readonly_fields = ("total_amount", "paid_amount", "status", "created_at", "updated_at")
    inlines = (InvoiceItemInline, PaymentInline)


@admin.register(InvoiceItem)
class InvoiceItemAdmin(admin.ModelAdmin):
    list_display = ("invoice", "service", "description", "quantity", "unit_price", "line_total")
    list_filter = ("service__category",)
    search_fields = ("invoice__invoice_code", "description", "service__code", "service__name")
    autocomplete_fields = ("invoice", "service")
    readonly_fields = ("line_total", "created_at", "updated_at")


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ("invoice", "paid_at", "amount", "method")
    list_filter = ("method", "paid_at")
    search_fields = ("invoice__invoice_code", "invoice__patient__full_name", "note")
    autocomplete_fields = ("invoice",)
    readonly_fields = ("created_at", "updated_at")


@admin.register(Medicine)
class MedicineAdmin(admin.ModelAdmin):
    list_display = ("medicine_code", "name", "strength", "unit", "active_ingredient", "is_active")
    list_filter = ("is_active", "unit")
    search_fields = ("medicine_code", "name", "active_ingredient", "strength")
    readonly_fields = ("created_at", "updated_at")


class SupplyLotInline(admin.TabularInline):
    model = SupplyLot
    extra = 0
    readonly_fields = ("current_quantity",)


@admin.register(Supply)
class SupplyAdmin(admin.ModelAdmin):
    list_display = ("supply_code", "name", "category", "unit", "minimum_quantity", "is_active")
    list_filter = ("category", "is_active")
    search_fields = ("supply_code", "name", "unit", "description")
    readonly_fields = ("created_at", "updated_at")
    inlines = (SupplyLotInline,)


@admin.register(SupplyLot)
class SupplyLotAdmin(admin.ModelAdmin):
    list_display = (
        "supply",
        "lot_number",
        "received_date",
        "expiry_date",
        "initial_quantity",
        "current_quantity",
    )
    list_filter = ("received_date", "expiry_date", "supply__category")
    search_fields = ("supply__supply_code", "supply__name", "lot_number", "supplier")
    autocomplete_fields = ("supply",)
    readonly_fields = ("current_quantity", "created_at", "updated_at")


@admin.register(SupplyExport)
class SupplyExportAdmin(admin.ModelAdmin):
    list_display = ("lot", "export_date", "quantity", "used_for", "performed_by")
    list_filter = ("export_date", "lot__supply__category")
    search_fields = ("lot__supply__supply_code", "lot__supply__name", "lot__lot_number", "used_for", "note")
    autocomplete_fields = ("lot", "performed_by")
    readonly_fields = ("created_at", "updated_at")


class PrescriptionItemInline(admin.TabularInline):
    model = PrescriptionItem
    extra = 1
    autocomplete_fields = ("medicine",)


@admin.register(Prescription)
class PrescriptionAdmin(admin.ModelAdmin):
    list_display = ("prescription_code", "patient", "doctor", "prescribed_at", "diagnosis")
    list_filter = ("prescribed_at", "doctor")
    search_fields = (
        "prescription_code",
        "patient__patient_code",
        "patient__full_name",
        "doctor__full_name",
        "diagnosis",
    )
    autocomplete_fields = ("patient", "appointment", "doctor")
    readonly_fields = ("created_at", "updated_at")
    inlines = (PrescriptionItemInline,)


@admin.register(PrescriptionItem)
class PrescriptionItemAdmin(admin.ModelAdmin):
    list_display = ("prescription", "medicine", "dosage", "quantity")
    list_filter = ("medicine",)
    search_fields = ("prescription__prescription_code", "medicine__name", "dosage", "instructions")
    autocomplete_fields = ("prescription", "medicine")
    readonly_fields = ("created_at", "updated_at")


@admin.register(ClinicHoliday)
class ClinicHolidayAdmin(admin.ModelAdmin):
    list_display = ("date", "name", "is_active")
    list_filter = ("is_active", "date")
    search_fields = ("name", "note")
    readonly_fields = ("created_at", "updated_at")


@admin.register(WorkShift)
class WorkShiftAdmin(admin.ModelAdmin):
    list_display = ("name", "weekday", "start_time", "end_time", "is_active")
    list_filter = ("weekday", "is_active")
    search_fields = ("name", "note")
    readonly_fields = ("created_at", "updated_at")


@admin.register(DoctorSchedule)
class DoctorScheduleAdmin(admin.ModelAdmin):
    list_display = ("doctor", "work_date", "shift", "status")
    list_filter = ("status", "work_date", "shift__weekday")
    search_fields = ("doctor__employee_code", "doctor__full_name", "note")
    autocomplete_fields = ("doctor", "shift")
    readonly_fields = ("created_at", "updated_at")


@admin.register(Appointment)
class AppointmentAdmin(admin.ModelAdmin):
    list_display = (
        "appointment_code",
        "patient",
        "doctor",
        "appointment_date",
        "start_time",
        "end_time",
        "status",
    )
    list_filter = ("status", "doctor_schedule__work_date", "service")
    search_fields = (
        "appointment_code",
        "patient__patient_code",
        "patient__full_name",
        "patient__phone",
        "doctor_schedule__doctor__full_name",
        "chief_complaint",
    )
    autocomplete_fields = ("patient", "doctor_schedule", "service")
    readonly_fields = ("created_at", "updated_at")

    @admin.display(description="Bác sĩ", ordering="doctor_schedule__doctor__full_name")
    def doctor(self, obj):
        return obj.doctor_schedule.doctor

    @admin.display(description="Ngày khám", ordering="doctor_schedule__work_date")
    def appointment_date(self, obj):
        return obj.doctor_schedule.work_date
