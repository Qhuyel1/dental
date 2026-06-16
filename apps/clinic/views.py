from datetime import datetime, time as datetime_time, timedelta
import base64
from decimal import Decimal
import hashlib
import hmac
import json
from io import BytesIO
import unicodedata
from urllib.parse import urlencode
from urllib import error as urllib_error
from urllib import request as urllib_request
from uuid import uuid4

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.conf import settings
from django.core.mail import EmailMessage
from django.http import HttpResponse, JsonResponse
from django.db import transaction
from django.db.models import Count, DecimalField, F, OuterRef, Q, Subquery, Sum, Value
from django.db.models.functions import Coalesce
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_time
from django.utils.decorators import method_decorator
from django.views.generic import (
    CreateView,
    DeleteView,
    DetailView,
    FormView,
    ListView,
    TemplateView,
    UpdateView,
    View,
)
from django.views.decorators.csrf import csrf_exempt

from core.mixins import StaffRequiredMixin

from .access import get_doctor_profile, is_doctor_user
from .forms import (
    AppointmentForm,
    ClinicHolidayForm,
    DoctorAppointmentForm,
    DoctorScheduleForm,
    InvoiceForm,
    InvoiceItemForm,
    MoMoPaymentForm,
    MedicineForm,
    PatientForm,
    PatientMedicalForm,
    PaymentForm,
    PriceListForm,
    ReceptionWalkInForm,
    PrescriptionForm,
    PrescriptionItemForm,
    ServiceCategoryForm,
    ServiceForm,
    ServicePriceForm,
    StaffForm,
    SupplyExportForm,
    SupplyForm,
    SupplyLotForm,
    WorkShiftForm,
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
from apps.portal.models import Conversation, Message


LIST_PAGE_SIZE = 10


def doctor_scoped_patients(queryset, user):
    doctor = get_doctor_profile(user)
    if not doctor:
        return queryset
    return queryset.filter(appointments__doctor_schedule__doctor=doctor).distinct()


def doctor_scoped_appointments(queryset, user):
    doctor = get_doctor_profile(user)
    if not doctor:
        return queryset
    return queryset.filter(doctor_schedule__doctor=doctor)


def doctor_scoped_prescriptions(queryset, user):
    doctor = get_doctor_profile(user)
    if not doctor:
        return queryset
    return queryset.filter(doctor=doctor)


def doctor_choices_for_user(user):
    queryset = Staff.objects.filter(role=Staff.Role.DOCTOR, is_active=True)
    doctor = get_doctor_profile(user)
    if doctor:
        queryset = queryset.filter(pk=doctor.pk)
    return queryset.order_by("full_name")


def get_pagination_query(request):
    query = request.GET.copy()
    query.pop("page", None)
    return query.urlencode()


def format_compact_number(value):
    value = value or 0
    if value >= 1_000_000_000:
        return f"{value / 1_000_000_000:.1f} tỷ".replace(".0", "")
    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f} triệu".replace(".0", "")
    if value >= 1_000:
        return f"{value / 1_000:.0f} nghìn"
    return f"{value:.0f}"


def build_bar_series(items):
    max_value = max((item["value"] for item in items), default=0)
    series = []
    for item in items:
        value = item["value"]
        height = int((value / max_value) * 100) if max_value else 0
        series.append(
            {
                **item,
                "height": max(height, 4) if value else 0,
                "display_value": format_compact_number(value),
            }
        )
    return series


def build_line_series(items, width=680, height=250):
    values = [float(item["value"] or 0) for item in items]
    max_value = max(values, default=0)
    plot_min = 0
    plot_max = max_value if max_value else 1
    left = 44
    right = 18
    top = 22
    bottom = 34
    plot_width = width - left - right
    plot_height = height - top - bottom
    baseline = height - bottom
    x_step = plot_width / (len(items) - 1) if len(items) > 1 else 0
    points = []

    for index, item in enumerate(items):
        value = float(item["value"] or 0)
        x = left + (x_step * index)
        y = baseline - ((value - plot_min) / (plot_max - plot_min) * plot_height)
        points.append(
            {
                **item,
                "x": round(x, 1),
                "y": round(y, 1),
                "display_value": format_compact_number(item["value"]),
                "show_label": index in {0, len(items) // 2, len(items) - 1},
            }
        )

    points_attr = " ".join(f"{point['x']},{point['y']}" for point in points)
    area_points = f"{left},{baseline} {points_attr} {width - right},{baseline}" if points else ""
    return {
        "width": width,
        "height": height,
        "left": left,
        "right_edge": width - right,
        "baseline": baseline,
        "grid_lines": [round(top + (plot_height * ratio), 1) for ratio in (0, 0.33, 0.66, 1)],
        "points": points,
        "points_attr": points_attr,
        "area_points": area_points,
        "max_label": format_compact_number(max((item["value"] for item in items), default=0)),
        "total_label": format_compact_number(sum((item["value"] for item in items), start=0)),
    }


def get_current_service_price_subquery():
    today = timezone.localdate()
    return (
        ServicePrice.objects.filter(
            service=OuterRef("pk"),
            price_list__is_active=True,
            price_list__effective_from__lte=today,
        )
        .filter(Q(price_list__effective_to__isnull=True) | Q(price_list__effective_to__gte=today))
        .order_by("-price_list__effective_from", "-price_list_id")
    )


def get_current_service_price(service):
    today = timezone.localdate()
    return (
        ServicePrice.objects.filter(
            service=service,
            price_list__is_active=True,
            price_list__effective_from__lte=today,
        )
        .filter(Q(price_list__effective_to__isnull=True) | Q(price_list__effective_to__gte=today))
        .order_by("-price_list__effective_from", "-price_list_id")
        .first()
    )


def format_vnd(value):
    return f"{value:,.0f}".replace(",", ".") + " VND"


def get_supply_stock_queryset():
    return Supply.objects.annotate(
        stock_quantity=Coalesce(
            Sum("lots__current_quantity"),
            Value(Decimal("0")),
            output_field=DecimalField(max_digits=12, decimal_places=2),
        )
    )


def normalize_pdf_text(value):
    text = unicodedata.normalize("NFKD", str(value))
    return text.encode("ascii", "ignore").decode("ascii")


def escape_pdf_text(value):
    return normalize_pdf_text(value).replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def build_simple_pdf(lines):
    content_lines = ["BT", "/F1 16 Tf", "50 800 Td"]
    if lines:
        content_lines.append(f"({escape_pdf_text(lines[0])}) Tj")
    content_lines.append("/F1 11 Tf")
    for line in lines[1:42]:
        content_lines.append("0 -18 Td")
        content_lines.append(f"({escape_pdf_text(str(line)[:105])}) Tj")
    content_lines.append("ET")
    content = "\n".join(content_lines).encode("latin-1", errors="ignore")

    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(content)).encode("ascii") + b" >>\nstream\n" + content + b"\nendstream",
    ]

    pdf = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, obj in enumerate(objects, start=1):
        offsets.append(len(pdf))
        pdf.extend(f"{index} 0 obj\n".encode("ascii"))
        pdf.extend(obj)
        pdf.extend(b"\nendobj\n")

    xref_offset = len(pdf)
    pdf.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    pdf.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        pdf.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    pdf.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF\n".encode("ascii")
    )
    return bytes(pdf)


def build_invoice_pdf(invoice):
    lines = [
        f"HOA DON {invoice.invoice_code}",
        f"Ngay lap: {invoice.issue_date:%d/%m/%Y}",
        f"Benh nhan: {invoice.patient.full_name} ({invoice.patient.patient_code})",
        f"Dien thoai: {invoice.patient.phone or '-'}",
        f"Hinh thuc: {invoice.get_payment_type_display()}",
        f"Trang thai: {invoice.get_status_display()}",
        "",
        "Chi phi dieu tri:",
    ]
    for item in invoice.items.select_related("service"):
        description = item.description or item.service.name
        lines.append(
            f"- {description}: {item.quantity} x {format_vnd(item.unit_price)} = {format_vnd(item.line_total)}"
        )
    lines.extend(
        [
            "",
            f"Tong chi phi: {format_vnd(invoice.total_amount)}",
            f"Da thanh toan: {format_vnd(invoice.paid_amount)}",
            f"Con no: {format_vnd(invoice.outstanding_amount)}",
            "",
            "Lich su thanh toan:",
        ]
    )
    for payment in invoice.payments.all():
        lines.append(f"- {payment.paid_at:%d/%m/%Y}: {format_vnd(payment.amount)} ({payment.get_method_display()})")
    if not invoice.payments.exists():
        lines.append("- Chua co thanh toan")
    if invoice.note:
        lines.extend(["", f"Ghi chu: {invoice.note}"])
    return build_simple_pdf(lines)


def get_momo_setting(name, default=""):
    return getattr(settings, name, default) or default


def is_placeholder_value(value):
    normalized = str(value or "").strip().lower()
    if not normalized:
        return True
    return normalized.startswith("your_") or normalized in {
        "your_email@gmail.com",
        "your_app_password",
        "your_sandbox_partner_code",
        "your_sandbox_access_key",
        "your_sandbox_secret_key",
    }


def is_momo_configured():
    if get_momo_setting("MOMO_SIMULATE"):
        return True
    return all(
        [
            not is_placeholder_value(get_momo_setting("MOMO_PARTNER_CODE")),
            not is_placeholder_value(get_momo_setting("MOMO_ACCESS_KEY")),
            not is_placeholder_value(get_momo_setting("MOMO_SECRET_KEY")),
            not is_placeholder_value(get_momo_setting("MOMO_CREATE_ENDPOINT")),
            not is_placeholder_value(get_momo_setting("MOMO_QUERY_ENDPOINT")),
        ]
    )


def make_momo_signature(raw_signature):
    secret_key = get_momo_setting("MOMO_SECRET_KEY")
    return hmac.new(secret_key.encode("utf-8"), raw_signature.encode("utf-8"), hashlib.sha256).hexdigest()


def build_momo_capture_wallet_payload(transaction_obj, request):
    partner_code = get_momo_setting("MOMO_PARTNER_CODE")
    access_key = get_momo_setting("MOMO_ACCESS_KEY")
    redirect_url = request.build_absolute_uri(
        reverse("clinic:momo-return") + f"?orderId={transaction_obj.order_id}"
    )
    ipn_url = request.build_absolute_uri(reverse("clinic:momo-ipn"))
    extra_data = base64.b64encode(
        json.dumps(
            {
                "invoice_id": transaction_obj.invoice_id,
                "invoice_code": transaction_obj.invoice.invoice_code,
                "transaction_id": transaction_obj.pk,
            }
        ).encode("utf-8")
    ).decode("ascii")
    raw_signature = (
        f"accessKey={access_key}&amount={int(transaction_obj.amount)}&extraData={extra_data}"
        f"&ipnUrl={ipn_url}&orderId={transaction_obj.order_id}&orderInfo=Thanh toan hoa don {transaction_obj.invoice.invoice_code}"
        f"&partnerCode={partner_code}&redirectUrl={redirect_url}"
        f"&requestId={transaction_obj.request_id}&requestType=captureWallet"
    )
    payload = {
        "partnerCode": partner_code,
        "partnerName": get_momo_setting("MOMO_PARTNER_NAME", "Dental Management"),
        "storeId": get_momo_setting("MOMO_STORE_ID", "DENTAL"),
        "storeName": get_momo_setting("MOMO_STORE_NAME", "Dental Management"),
        "requestId": transaction_obj.request_id,
        "amount": int(transaction_obj.amount),
        "orderId": transaction_obj.order_id,
        "orderInfo": f"Thanh toan hoa don {transaction_obj.invoice.invoice_code}",
        "redirectUrl": redirect_url,
        "ipnUrl": ipn_url,
        "lang": "vi",
        "requestType": "captureWallet",
        "autoCapture": True,
        "extraData": extra_data,
        "userInfo": {
            "name": transaction_obj.invoice.patient.full_name,
            "phoneNumber": transaction_obj.invoice.patient.phone,
            "email": transaction_obj.customer_email or transaction_obj.invoice.patient.email,
        },
        "signature": make_momo_signature(raw_signature),
    }
    return payload


def call_json_api(url, payload, timeout=None):
    timeout = timeout or int(get_momo_setting("MOMO_TIMEOUT_SECONDS", 30))
    request = urllib_request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib_request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def create_momo_transaction(transaction_obj, request):
    if get_momo_setting("MOMO_SIMULATE"):
        pay_url = request.build_absolute_uri(
            reverse("clinic:momo-simulate-payment", kwargs={"pk": transaction_obj.pk})
        )
        response_data = {
            "resultCode": 0,
            "message": "Simulated transaction created successfully.",
            "payUrl": pay_url,
            "deeplink": pay_url,
            "qrCodeUrl": "",
        }
        transaction_obj.raw_create_response = response_data
        transaction_obj.result_code = 0
        transaction_obj.provider_message = "Simulated transaction created."
        transaction_obj.pay_url = pay_url
        transaction_obj.deeplink = pay_url
        transaction_obj.qr_code_url = ""
        transaction_obj.save(
            update_fields=[
                "raw_create_response",
                "result_code",
                "provider_message",
                "pay_url",
                "deeplink",
                "qr_code_url",
                "status",
                "updated_at",
            ]
        )
        return response_data

    payload = build_momo_capture_wallet_payload(transaction_obj, request)
    response_data = call_json_api(get_momo_setting("MOMO_CREATE_ENDPOINT"), payload)
    transaction_obj.raw_create_response = response_data
    transaction_obj.result_code = response_data.get("resultCode")
    transaction_obj.provider_message = response_data.get("message", "")
    transaction_obj.pay_url = response_data.get("payUrl", "")
    transaction_obj.deeplink = response_data.get("deeplink") or response_data.get("deeplinkMiniApp", "")
    transaction_obj.qr_code_url = response_data.get("qrCodeUrl", "")
    if response_data.get("resultCode") != 0:
        transaction_obj.status = PaymentTransaction.Status.FAILED
    transaction_obj.save(
        update_fields=[
            "raw_create_response",
            "result_code",
            "provider_message",
            "pay_url",
            "deeplink",
            "qr_code_url",
            "status",
            "updated_at",
        ]
    )
    return response_data


def build_momo_ipn_signature(payload):
    return (
        f"accessKey={get_momo_setting('MOMO_ACCESS_KEY')}&amount={payload.get('amount', '')}"
        f"&extraData={payload.get('extraData', '')}&message={payload.get('message', '')}"
        f"&orderId={payload.get('orderId', '')}&orderInfo={payload.get('orderInfo', '')}"
        f"&orderType={payload.get('orderType', '')}&partnerCode={payload.get('partnerCode', '')}"
        f"&payType={payload.get('payType', '')}&requestId={payload.get('requestId', '')}"
        f"&responseTime={payload.get('responseTime', '')}&resultCode={payload.get('resultCode', '')}"
        f"&transId={payload.get('transId', '')}"
    )


def verify_momo_ipn_signature(payload):
    signature = payload.get("signature", "")
    if not signature:
        return False
    return hmac.compare_digest(signature, make_momo_signature(build_momo_ipn_signature(payload)))


def build_momo_query_payload(transaction_obj, request_id):
    access_key = get_momo_setting("MOMO_ACCESS_KEY")
    raw_signature = (
        f"accessKey={access_key}&orderId={transaction_obj.order_id}"
        f"&partnerCode={get_momo_setting('MOMO_PARTNER_CODE')}&requestId={request_id}"
    )
    return {
        "partnerCode": get_momo_setting("MOMO_PARTNER_CODE"),
        "requestId": request_id,
        "orderId": transaction_obj.order_id,
        "lang": "vi",
        "signature": make_momo_signature(raw_signature),
    }


def query_momo_transaction(transaction_obj):
    if get_momo_setting("MOMO_SIMULATE"):
        result_code = 0 if transaction_obj.status == PaymentTransaction.Status.SUCCESS else (49 if transaction_obj.status == PaymentTransaction.Status.FAILED else 1000)
        message = "Successful." if result_code == 0 else ("Failed." if result_code == 49 else "Pending.")
        response_data = {
            "partnerCode": get_momo_setting("MOMO_PARTNER_CODE", "MOMO"),
            "orderId": transaction_obj.order_id,
            "requestId": f"SIMREQ{uuid4().hex[:18]}",
            "amount": int(transaction_obj.amount),
            "transId": transaction_obj.trans_id or f"SIM{uuid4().hex[:12]}",
            "resultCode": result_code,
            "message": message,
        }
        transaction_obj.raw_ipn_payload = response_data
        transaction_obj.result_code = result_code
        transaction_obj.provider_message = message
        transaction_obj.trans_id = str(response_data.get("transId", ""))
        transaction_obj.save(update_fields=["raw_ipn_payload", "result_code", "provider_message", "trans_id", "updated_at"])
        return response_data

    query_request_id = f"QUERY{uuid4().hex[:24]}"
    response_data = call_json_api(
        get_momo_setting("MOMO_QUERY_ENDPOINT"),
        build_momo_query_payload(transaction_obj, query_request_id),
    )
    transaction_obj.raw_ipn_payload = response_data
    transaction_obj.result_code = response_data.get("resultCode")
    transaction_obj.provider_message = response_data.get("message", "")
    transaction_obj.trans_id = str(response_data.get("transId", "") or "")
    transaction_obj.save(update_fields=["raw_ipn_payload", "result_code", "provider_message", "trans_id", "updated_at"])
    return response_data


def build_invoice_receipt_email(invoice, payment_obj, payment_transaction):
    lines = [
        f"Kinh gui {invoice.patient.full_name},",
        "",
        "Phong kham da ghi nhan thanh toan thanh cong qua MoMo.",
        f"Hoa don: {invoice.invoice_code}",
        f"So tien vua thanh toan: {format_vnd(payment_obj.amount)}",
        f"Ngay thanh toan: {payment_obj.paid_at:%d/%m/%Y}",
        f"Ma giao dich MoMo: {payment_transaction.trans_id or payment_transaction.order_id}",
        f"Tong hoa don: {format_vnd(invoice.total_amount)}",
        f"Da thanh toan: {format_vnd(invoice.paid_amount)}",
        f"Con no: {format_vnd(invoice.outstanding_amount)}",
        "",
        "Bien nhan PDF duoc dinh kem trong email nay.",
        "",
        "Dental Management",
    ]
    return "\n".join(lines)


def send_invoice_receipt_email(payment_transaction_id):
    transaction_obj = PaymentTransaction.objects.select_related("invoice__patient", "payment").filter(
        pk=payment_transaction_id
    ).first()
    if not transaction_obj or not transaction_obj.customer_email or not transaction_obj.payment_id:
        return

    invoice = transaction_obj.invoice
    payment_obj = transaction_obj.payment
    subject = f"Bien nhan thanh toan {invoice.invoice_code}"
    body = build_invoice_receipt_email(invoice, payment_obj, transaction_obj)
    email = EmailMessage(
        subject=subject,
        body=body,
        from_email=get_momo_setting("DEFAULT_FROM_EMAIL", "no-reply@dental.local"),
        to=[transaction_obj.customer_email],
    )
    email.attach(
        f"{invoice.invoice_code}.pdf",
        build_invoice_pdf(invoice),
        "application/pdf",
    )
    try:
        email.send(fail_silently=False)
        PaymentTransaction.objects.filter(pk=transaction_obj.pk).update(
            receipt_email_sent_at=timezone.now(),
            receipt_email_error="",
            updated_at=timezone.now(),
        )
    except Exception as exc:
        PaymentTransaction.objects.filter(pk=transaction_obj.pk).update(
            receipt_email_error=str(exc)[:1000],
            updated_at=timezone.now(),
        )


def get_payment_date_from_payload(payload):
    response_time = payload.get("responseTime")
    if response_time:
        try:
            timestamp = int(response_time) / 1000
            local_zone = timezone.get_current_timezone()
            return timezone.localtime(datetime.fromtimestamp(timestamp, tz=local_zone)).date()
        except Exception:
            pass
    return timezone.localdate()


def apply_momo_transaction_result(transaction_obj, payload, request=None):
    with transaction.atomic():
        locked_transaction = PaymentTransaction.objects.select_for_update().select_related("invoice", "payment").get(
            pk=transaction_obj.pk
        )
        locked_transaction.raw_ipn_payload = payload
        locked_transaction.result_code = payload.get("resultCode")
        locked_transaction.provider_message = payload.get("message", "")
        locked_transaction.trans_id = str(payload.get("transId", "") or "")

        if payload.get("resultCode") == 0:
            if not locked_transaction.payment_id:
                payment_obj = Payment(
                    invoice=locked_transaction.invoice,
                    paid_at=get_payment_date_from_payload(payload),
                    amount=locked_transaction.amount,
                    method=Payment.Method.MOMO,
                    note=f"MoMo {locked_transaction.order_id}",
                )
                try:
                    payment_obj.full_clean()
                    payment_obj.save()
                    locked_transaction.payment = payment_obj
                    locked_transaction.status = PaymentTransaction.Status.SUCCESS
                    locked_transaction.paid_at = timezone.now()
                except ValidationError as exc:
                    locked_transaction.status = PaymentTransaction.Status.REVIEW
                    locked_transaction.provider_message = "; ".join(
                        error
                        for errors in exc.message_dict.values()
                        for error in errors
                    ) if hasattr(exc, "message_dict") else "; ".join(exc.messages)
            else:
                locked_transaction.status = PaymentTransaction.Status.SUCCESS
        else:
            locked_transaction.status = PaymentTransaction.Status.FAILED

        locked_transaction.save(
            update_fields=[
                "raw_ipn_payload",
                "result_code",
                "provider_message",
                "trans_id",
                "payment",
                "status",
                "paid_at",
                "updated_at",
            ]
        )

    if locked_transaction.status == PaymentTransaction.Status.SUCCESS and locked_transaction.customer_email:
        transaction.on_commit(lambda: send_invoice_receipt_email(locked_transaction.pk))

    try:
        from apps.users.models import SecurityEvent

        SecurityEvent.record(
            SecurityEvent.Action.UPDATE,
            request=request,
            username="momo_ipn" if request is None or not getattr(request, "user", None) else "",
            target=locked_transaction,
            message="MoMo cap nhat ket qua giao dich.",
            metadata={
                "result_code": locked_transaction.result_code,
                "status": locked_transaction.status,
                "order_id": locked_transaction.order_id,
                "payment_id": locked_transaction.payment_id,
            },
        )
    except Exception:
        pass

    return locked_transaction


def build_qr_svg(data):
    if not data:
        return ""
    try:
        import qrcode
        import qrcode.image.svg

        qr_image = qrcode.make(data, image_factory=qrcode.image.svg.SvgPathImage, box_size=8)
        output = BytesIO()
        qr_image.save(output)
        return output.getvalue().decode("utf-8")
    except Exception:
        return ""


def build_appointment_ticket_pdf(appointment):
    lines = [
        "PHIEU TIEP DON",
        f"So thu tu: {appointment.queue_number or '-'}",
        f"Ngay: {appointment.appointment_date:%d/%m/%Y}",
        f"Gio: {appointment.start_time:%H:%M} - {appointment.end_time:%H:%M}",
        f"Benh nhan: {appointment.patient.full_name} ({appointment.patient.patient_code})",
        f"Dien thoai: {appointment.patient.phone or '-'}",
        f"Bac si: {appointment.doctor.full_name}",
        f"Ca: {appointment.doctor_schedule.shift.name}",
        f"Nguon tiep nhan: {appointment.get_arrival_type_display()}",
        f"Loai luot kham: {appointment.get_visit_type_display()}",
        f"Muc uu tien: {appointment.get_priority_level_display()}",
        f"Ly do kham: {appointment.chief_complaint or '-'}",
    ]
    if appointment.checked_in_at:
        lines.append(f"Check-in luc: {timezone.localtime(appointment.checked_in_at):%H:%M %d/%m/%Y}")
    if appointment.note:
        lines.extend(["", f"Ghi chu: {appointment.note}"])
    return build_simple_pdf(lines)


def get_medical_alerts_for_patient(patient):
    medical_alerts = []
    if patient.allergy_note:
        medical_alerts.append("Co ghi chu di ung")
    if patient.medical_history:
        medical_alerts.append("Co tien su benh")
    if patient.current_medications:
        medical_alerts.append("Dang dung thuoc")
    return medical_alerts


def get_admin_alerts_for_patient(patient):
    admin_alerts = []
    if not patient.phone:
        admin_alerts.append("Thieu so dien thoai")
    if not patient.national_id:
        admin_alerts.append("Thieu CCCD/CMND")
    if not patient.email:
        admin_alerts.append("Thieu email")
    outstanding_invoices = [invoice for invoice in patient.invoices.all() if invoice.status != Invoice.Status.PAID]
    if outstanding_invoices:
        admin_alerts.append(f"Con no {len(outstanding_invoices)} hoa don")
    return admin_alerts


def get_priority_rank(priority_level):
    return {
        Appointment.PriorityLevel.URGENT: 0,
        Appointment.PriorityLevel.PRIORITY: 1,
        Appointment.PriorityLevel.NORMAL: 2,
    }.get(priority_level, 99)


def minutes_from_time(value):
    return value.hour * 60 + value.minute


def floor_to_slot(minutes, interval=30):
    return minutes - (minutes % interval)


def ceil_to_slot(minutes, interval=30):
    return ((minutes + interval - 1) // interval) * interval


def time_from_minutes(minutes):
    return datetime_time(hour=minutes // 60, minute=minutes % 60)


def get_next_queue_number(doctor_schedule):
    latest_queue_number = (
        Appointment.objects.filter(
            doctor_schedule__work_date=doctor_schedule.work_date,
            doctor_schedule__doctor=doctor_schedule.doctor,
            queue_number__isnull=False,
        )
        .order_by("-queue_number")
        .values_list("queue_number", flat=True)
        .first()
        or 0
    )
    return latest_queue_number + 1


def find_next_walk_in_slot(doctor_schedule, duration_minutes=30):
    duration_minutes = max(duration_minutes or 30, 15)
    today = timezone.localdate()
    shift_start = minutes_from_time(doctor_schedule.shift.start_time)
    shift_end = minutes_from_time(doctor_schedule.shift.end_time)
    cursor = shift_start

    if doctor_schedule.work_date == today:
        now_time = timezone.localtime().time().replace(second=0, microsecond=0)
        cursor = max(cursor, ceil_to_slot(minutes_from_time(now_time), 30))

    occupied_slots = doctor_schedule.appointments.exclude(
        status__in=[Appointment.Status.CANCELLED, Appointment.Status.NO_SHOW]
    ).order_by("start_time")

    for appointment in occupied_slots:
        appointment_start = minutes_from_time(appointment.start_time)
        appointment_end = minutes_from_time(appointment.end_time)

        if cursor + duration_minutes <= appointment_start:
            return time_from_minutes(cursor), time_from_minutes(cursor + duration_minutes)

        if appointment_end > cursor:
            cursor = ceil_to_slot(appointment_end, 30)

    if cursor + duration_minutes <= shift_end:
        return time_from_minutes(cursor), time_from_minutes(cursor + duration_minutes)

    return None, None


class SystemDashboardView(StaffRequiredMixin, TemplateView):
    template_name = "system/dashboard.html"
    permission_required = "users.view_dashboard"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        today = timezone.localdate()
        month_start = today.replace(day=1)
        next_month_start = self._get_next_month_start(month_start)
        previous_month_end = month_start - timedelta(days=1)
        previous_month_start = previous_month_end.replace(day=1)
        year_start = today.replace(month=1, day=1)
        can_view_finance = self.request.user.has_perm("clinic.view_invoice")
        can_view_stock = self.request.user.has_perm("clinic.view_supply")
        revenue_today = self._sum_payments(today, today) if can_view_finance else 0
        revenue_month = self._sum_payments(month_start, today) if can_view_finance else 0
        revenue_year = self._sum_payments(year_start, today) if can_view_finance else 0
        previous_month_revenue = self._sum_payments(previous_month_start, previous_month_end) if can_view_finance else 0
        patient_queryset = doctor_scoped_patients(Patient.objects.all(), self.request.user)
        appointment_queryset = doctor_scoped_appointments(Appointment.objects.all(), self.request.user)
        prescription_queryset = doctor_scoped_prescriptions(Prescription.objects.all(), self.request.user)
        doctor_schedule_queryset = DoctorSchedule.objects.all()
        doctor = get_doctor_profile(self.request.user)
        if doctor:
            doctor_schedule_queryset = doctor_schedule_queryset.filter(doctor=doctor)
        current_month_appointments = appointment_queryset.filter(
            doctor_schedule__work_date__gte=month_start,
            doctor_schedule__work_date__lt=next_month_start,
        )
        context.update(
            {
                "patient_count": patient_queryset.count(),
                "staff_count": Staff.objects.count(),
                "doctor_count": Staff.objects.filter(role=Staff.Role.DOCTOR).count(),
                "service_count": Service.objects.count(),
                "category_count": ServiceCategory.objects.count(),
                "price_list_count": PriceList.objects.count(),
                "active_price_list_count": PriceList.objects.filter(is_active=True).count(),
                "invoice_count": Invoice.objects.count() if can_view_finance else 0,
                "outstanding_invoice_count": Invoice.objects.filter(status=Invoice.Status.OUTSTANDING).count() if can_view_finance else 0,
                "medicine_count": Medicine.objects.filter(is_active=True).count(),
                "prescription_count": prescription_queryset.count(),
                "supply_count": Supply.objects.filter(is_active=True).count() if can_view_stock else 0,
                "low_stock_supply_count": get_supply_stock_queryset()
                .filter(is_active=True, minimum_quantity__gt=0, stock_quantity__lte=F("minimum_quantity"))
                .count() if can_view_stock else 0,
                "expired_supply_lot_count": SupplyLot.objects.filter(
                    current_quantity__gt=0,
                    expiry_date__lt=today,
                ).count() if can_view_stock else 0,
                "expiring_supply_lot_count": SupplyLot.objects.filter(
                    current_quantity__gt=0,
                    expiry_date__gte=today,
                    expiry_date__lte=today + timedelta(days=30),
                ).count() if can_view_stock else 0,
                "revenue_today": revenue_today,
                "revenue_month": revenue_month,
                "revenue_year": revenue_year,
                "revenue_month_change_percent": self._calculate_change_percent(
                    revenue_month,
                    previous_month_revenue,
                ),
                "new_patient_today_count": patient_queryset.filter(created_at__date=today).count(),
                "new_patient_month_count": patient_queryset.filter(
                    created_at__date__gte=month_start,
                    created_at__date__lt=next_month_start,
                ).count(),
                "new_patient_year_count": patient_queryset.filter(created_at__date__gte=year_start).count(),
                "completed_appointment_month_count": current_month_appointments.filter(
                    status=Appointment.Status.COMPLETED,
                ).count(),
                "cancelled_appointment_month_count": current_month_appointments.filter(
                    status=Appointment.Status.CANCELLED,
                ).count(),
                "holiday_count": ClinicHoliday.objects.filter(is_active=True).count(),
                "work_shift_count": WorkShift.objects.filter(is_active=True).count(),
                "doctor_schedule_count": doctor_schedule_queryset.filter(
                    work_date__gte=timezone.localdate(),
                    status=DoctorSchedule.Status.REGISTERED,
                ).count(),
                "upcoming_appointment_count": appointment_queryset.filter(
                    doctor_schedule__work_date__gte=timezone.localdate(),
                )
                .exclude(status__in=[Appointment.Status.CANCELLED, Appointment.Status.NO_SHOW])
                .count(),
            }
        )
        context.update(
            self._build_report_context(
                today,
                month_start,
                next_month_start,
                year_start,
                patient_queryset,
                appointment_queryset,
                can_view_finance,
            )
        )
        return context

    def _sum_payments(self, start_date, end_date):
        return (
            Payment.objects.filter(paid_at__gte=start_date, paid_at__lte=end_date).aggregate(total=Sum("amount"))[
                "total"
            ]
            or 0
        )

    def _get_next_month_start(self, month_start):
        if month_start.month == 12:
            return month_start.replace(year=month_start.year + 1, month=1)
        return month_start.replace(month=month_start.month + 1)

    def _calculate_change_percent(self, current_value, previous_value):
        if previous_value:
            return int(((current_value - previous_value) / previous_value) * 100)
        return 100 if current_value else 0

    def _build_report_context(self, today, month_start, next_month_start, year_start, patient_queryset, appointment_queryset, can_view_finance):
        daily_revenue = self._build_daily_revenue(today) if can_view_finance else build_bar_series([])
        monthly_revenue = self._build_monthly_revenue(today) if can_view_finance else build_bar_series([])
        yearly_revenue = self._build_yearly_revenue(today) if can_view_finance else build_bar_series([])
        patient_series = self._build_new_patient_series(today, patient_queryset)
        appointment_status_report = self._build_appointment_status_report(month_start, next_month_start, appointment_queryset)
        return {
            "daily_revenue_chart": daily_revenue,
            "monthly_revenue_chart": monthly_revenue,
            "monthly_revenue_trend_chart": build_line_series(monthly_revenue, width=660, height=260),
            "yearly_revenue_chart": yearly_revenue,
            "new_patient_chart": patient_series,
            "revenue_line_chart": self._build_revenue_line_chart(today) if can_view_finance else build_line_series([]),
            "appointment_line_chart": self._build_appointment_line_chart(today, appointment_queryset),
            "appointment_status_report": appointment_status_report,
            "top_services": self._build_top_services(month_start, next_month_start) if can_view_finance else [],
            "doctor_performance": self._build_doctor_performance(month_start, next_month_start) if can_view_finance else [],
            "report_month_label": f"{month_start:%m/%Y}",
        }

    def _build_daily_revenue(self, today):
        start_date = today - timedelta(days=6)
        totals = {
            row["paid_at"]: row["total"] or 0
            for row in Payment.objects.filter(paid_at__gte=start_date, paid_at__lte=today)
            .values("paid_at")
            .annotate(total=Sum("amount"))
        }
        return build_bar_series(
            [
                {
                    "label": (start_date + timedelta(days=offset)).strftime("%d/%m"),
                    "value": totals.get(start_date + timedelta(days=offset), 0),
                }
                for offset in range(7)
            ]
        )

    def _build_revenue_line_chart(self, today):
        start_date = today - timedelta(days=13)
        totals = {
            row["paid_at"]: row["total"] or 0
            for row in Payment.objects.filter(paid_at__gte=start_date, paid_at__lte=today)
            .values("paid_at")
            .annotate(total=Sum("amount"))
        }
        return build_line_series(
            [
                {
                    "label": (start_date + timedelta(days=offset)).strftime("%d/%m"),
                    "value": totals.get(start_date + timedelta(days=offset), 0),
                }
                for offset in range(14)
            ]
        )

    def _build_appointment_line_chart(self, today, appointment_queryset):
        start_date = today - timedelta(days=13)
        totals = {
            row["doctor_schedule__work_date"]: row["total"]
            for row in appointment_queryset.filter(
                doctor_schedule__work_date__gte=start_date,
                doctor_schedule__work_date__lte=today,
            )
            .values("doctor_schedule__work_date")
            .annotate(total=Count("id"))
        }
        return build_line_series(
            [
                {
                    "label": (start_date + timedelta(days=offset)).strftime("%d/%m"),
                    "value": totals.get(start_date + timedelta(days=offset), 0),
                }
                for offset in range(14)
            ],
            width=420,
            height=210,
        )

    def _build_monthly_revenue(self, today):
        totals = {
            row["paid_at__month"]: row["total"] or 0
            for row in Payment.objects.filter(paid_at__year=today.year)
            .values("paid_at__month")
            .annotate(total=Sum("amount"))
        }
        return build_bar_series(
            [{"label": f"T{month}", "value": totals.get(month, 0)} for month in range(1, 13)]
        )

    def _build_yearly_revenue(self, today):
        start_year = today.year - 4
        totals = {
            row["paid_at__year"]: row["total"] or 0
            for row in Payment.objects.filter(paid_at__year__gte=start_year, paid_at__year__lte=today.year)
            .values("paid_at__year")
            .annotate(total=Sum("amount"))
        }
        return build_bar_series(
            [{"label": str(year), "value": totals.get(year, 0)} for year in range(start_year, today.year + 1)]
        )

    def _build_new_patient_series(self, today, patient_queryset):
        start_date = today - timedelta(days=6)
        totals = {
            row["created_at__date"]: row["total"]
            for row in patient_queryset.filter(created_at__date__gte=start_date, created_at__date__lte=today)
            .values("created_at__date")
            .annotate(total=Count("id"))
        }
        return build_bar_series(
            [
                {
                    "label": (start_date + timedelta(days=offset)).strftime("%d/%m"),
                    "value": totals.get(start_date + timedelta(days=offset), 0),
                }
                for offset in range(7)
            ]
        )

    def _build_appointment_status_report(self, month_start, next_month_start, appointment_queryset):
        appointments = appointment_queryset.filter(
            doctor_schedule__work_date__gte=month_start,
            doctor_schedule__work_date__lt=next_month_start,
        )
        completed = appointments.filter(status=Appointment.Status.COMPLETED).count()
        cancelled = appointments.filter(status=Appointment.Status.CANCELLED).count()
        no_show = appointments.filter(status=Appointment.Status.NO_SHOW).count()
        active = appointments.exclude(
            status__in=[
                Appointment.Status.COMPLETED,
                Appointment.Status.CANCELLED,
                Appointment.Status.NO_SHOW,
            ],
        ).count()
        total = completed + cancelled + no_show + active

        def percent(value):
            return int((value / total) * 100) if total else 0

        return {
            "completed": completed,
            "cancelled": cancelled,
            "no_show": no_show,
            "active": active,
            "total": total,
            "completed_percent": percent(completed),
            "cancelled_percent": percent(cancelled),
            "no_show_percent": percent(no_show),
            "active_percent": percent(active),
        }

    def _build_top_services(self, month_start, next_month_start):
        services = (
            InvoiceItem.objects.filter(
                invoice__issue_date__gte=month_start,
                invoice__issue_date__lt=next_month_start,
                service__isnull=False,
            )
            .values("service__name")
            .annotate(usage_count=Sum("quantity"), revenue=Sum("line_total"))
            .order_by("-usage_count", "-revenue")[:6]
        )
        max_usage = max((item["usage_count"] or 0 for item in services), default=0)
        return [
            {
                "name": item["service__name"],
                "usage_count": item["usage_count"] or 0,
                "revenue": item["revenue"] or 0,
                "bar_width": int(((item["usage_count"] or 0) / max_usage) * 100) if max_usage else 0,
            }
            for item in services
        ]

    def _build_doctor_performance(self, month_start, next_month_start):
        doctors = Staff.objects.filter(role=Staff.Role.DOCTOR, is_active=True).order_by("full_name")
        rows = []
        for doctor in doctors:
            appointments = Appointment.objects.filter(
                doctor_schedule__doctor=doctor,
                doctor_schedule__work_date__gte=month_start,
                doctor_schedule__work_date__lt=next_month_start,
            )
            total = appointments.count()
            completed = appointments.filter(status=Appointment.Status.COMPLETED).count()
            cancelled = appointments.filter(status=Appointment.Status.CANCELLED).count()
            revenue = (
                Payment.objects.filter(
                    invoice__appointment__doctor_schedule__doctor=doctor,
                    paid_at__gte=month_start,
                    paid_at__lt=next_month_start,
                ).aggregate(total=Sum("amount"))["total"]
                or 0
            )
            completion_rate = int((completed / total) * 100) if total else 0
            rows.append(
                {
                    "doctor": doctor,
                    "total": total,
                    "completed": completed,
                    "cancelled": cancelled,
                    "completion_rate": completion_rate,
                    "revenue": revenue,
                }
            )
        return sorted(rows, key=lambda item: (item["completed"], item["revenue"]), reverse=True)[:8]


class PatientListView(StaffRequiredMixin, ListView):
    model = Patient
    template_name = "clinic/patient_list.html"
    context_object_name = "patients"
    paginate_by = LIST_PAGE_SIZE

    def get_queryset(self):
        queryset = doctor_scoped_patients(Patient.objects.all(), self.request.user).order_by("full_name")
        keyword = self.request.GET.get("q", "").strip()
        gender = self.request.GET.get("gender", "").strip()
        status = self.request.GET.get("status", "").strip()
        if keyword:
            queryset = queryset.filter(
                Q(patient_code__icontains=keyword)
                | Q(full_name__icontains=keyword)
                | Q(national_id__icontains=keyword)
                | Q(phone__icontains=keyword)
                | Q(email__icontains=keyword)
                | Q(address__icontains=keyword)
                | Q(emergency_contact_phone__icontains=keyword)
            )
        if gender:
            queryset = queryset.filter(gender=gender)
        if status == "active":
            queryset = queryset.filter(is_active=True)
        elif status == "inactive":
            queryset = queryset.filter(is_active=False)
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["keyword"] = self.request.GET.get("q", "").strip()
        context["selected_gender"] = self.request.GET.get("gender", "").strip()
        context["selected_status"] = self.request.GET.get("status", "").strip()
        context["gender_choices"] = Patient.Gender.choices
        context["pagination_query"] = get_pagination_query(self.request)
        return context


class PatientDetailView(StaffRequiredMixin, DetailView):
    model = Patient
    template_name = "clinic/patient_detail.html"
    context_object_name = "patient"

    def get_queryset(self):
        queryset = Patient.objects.select_related("user", "user__security_profile").prefetch_related(
            "user__groups",
            "appointments__doctor_schedule__doctor",
            "appointments__doctor_schedule__shift",
            "appointments__service",
            "invoices",
            "prescriptions__doctor",
        )
        return doctor_scoped_patients(queryset, self.request.user)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        credential_notice = self.request.session.get("patient_created_credentials")
        if credential_notice and credential_notice.get("patient_id") == self.object.pk:
            context["created_credentials"] = credential_notice
            del self.request.session["patient_created_credentials"]
            self.request.session.modified = True
        context["must_change_password"] = (
            bool(self.object.user_id)
            and hasattr(self.object.user, "security_profile")
            and self.object.user.security_profile.must_change_password
        )
        appointments = doctor_scoped_appointments(
            self.object.appointments.select_related(
                "doctor_schedule__doctor",
                "doctor_schedule__shift",
                "service",
            ),
            self.request.user,
        ).order_by("-doctor_schedule__work_date", "-start_time")
        context["appointments"] = appointments[:10]
        if self.request.user.has_perm("clinic.view_invoice"):
            context["invoices"] = self.object.invoices.order_by("-issue_date", "-id")[:10]
        context["prescriptions"] = doctor_scoped_prescriptions(
            self.object.prescriptions.select_related("doctor"),
            self.request.user,
        ).order_by(
            "-prescribed_at",
            "-id",
        )[:10]
        return context


class PatientCreateView(StaffRequiredMixin, CreateView):
    model = Patient
    form_class = PatientForm
    template_name = "clinic/patient_form.html"

    def get_success_url(self):
        return reverse("clinic:patient-detail", kwargs={"pk": self.object.pk})

    def form_valid(self, form):
        response = super().form_valid(form)
        if form.generated_user:
            self.request.session["patient_created_credentials"] = {
                "patient_id": self.object.pk,
                "username": form.generated_username,
                "password": form.generated_password,
            }
            messages.warning(
                self.request,
                "Đã tạo hồ sơ và tài khoản đăng nhập cho bệnh nhân. Mật khẩu khởi tạo chỉ hiển thị một lần ở trang chi tiết.",
            )
        else:
            messages.success(self.request, "Đã thêm bệnh nhân mới.")
        return response


class PatientUpdateView(StaffRequiredMixin, UpdateView):
    model = Patient
    form_class = PatientForm
    template_name = "clinic/patient_form.html"

    def get_form_class(self):
        if is_doctor_user(self.request.user):
            return PatientMedicalForm
        return super().get_form_class()

    def get_queryset(self):
        return doctor_scoped_patients(super().get_queryset(), self.request.user)

    def get_success_url(self):
        return reverse("clinic:patient-detail", kwargs={"pk": self.object.pk})

    def form_valid(self, form):
        response = super().form_valid(form)
        if form.generated_user:
            self.request.session["patient_created_credentials"] = {
                "patient_id": self.object.pk,
                "username": form.generated_username,
                "password": form.generated_password,
            }
            messages.warning(
                self.request,
                "Đã tạo tài khoản đăng nhập cho hồ sơ bệnh nhân này. Mật khẩu khởi tạo chỉ hiển thị một lần ở trang chi tiết.",
            )
        else:
            messages.success(self.request, "Đã cập nhật thông tin bệnh nhân.")
        return response


class PatientDeleteView(StaffRequiredMixin, DeleteView):
    model = Patient
    template_name = "clinic/patient_confirm_delete.html"
    success_url = reverse_lazy("clinic:patient-list")

    def form_valid(self, form):
        patient = self.get_object()
        if patient.user_id and patient.user.is_active:
            patient.user.is_active = False
            patient.user.save(update_fields=["is_active"])
        messages.success(self.request, "Đã xóa hồ sơ bệnh nhân.")
        return super().form_valid(form)


class StaffListView(StaffRequiredMixin, ListView):
    model = Staff
    template_name = "clinic/staff_list.html"
    context_object_name = "staff_members"
    paginate_by = LIST_PAGE_SIZE

    def get_queryset(self):
        queryset = Staff.objects.order_by("full_name")
        keyword = self.request.GET.get("q", "").strip()
        role = self.request.GET.get("role", "").strip()
        status = self.request.GET.get("status", "").strip()
        if keyword:
            queryset = queryset.filter(
                Q(employee_code__icontains=keyword)
                | Q(full_name__icontains=keyword)
                | Q(phone__icontains=keyword)
                | Q(email__icontains=keyword)
                | Q(address__icontains=keyword)
                | Q(degree__icontains=keyword)
                | Q(specialization__icontains=keyword)
                | Q(license_number__icontains=keyword)
            )
        if role:
            queryset = queryset.filter(role=role)
        if status == "active":
            queryset = queryset.filter(is_active=True)
        elif status == "inactive":
            queryset = queryset.filter(is_active=False)
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["keyword"] = self.request.GET.get("q", "").strip()
        context["selected_role"] = self.request.GET.get("role", "").strip()
        context["selected_status"] = self.request.GET.get("status", "").strip()
        context["role_choices"] = Staff.Role.choices
        context["pagination_query"] = get_pagination_query(self.request)
        return context


class StaffDetailView(StaffRequiredMixin, DetailView):
    model = Staff
    template_name = "clinic/staff_detail.html"
    context_object_name = "staff"

    def get_queryset(self):
        return Staff.objects.select_related("user", "user__security_profile").prefetch_related(
            "user__groups",
            "doctor_schedules__shift",
            "doctor_schedules__appointments__patient",
            "doctor_schedules__appointments__service",
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        credential_notice = self.request.session.get("staff_created_credentials")
        if credential_notice and credential_notice.get("staff_id") == self.object.pk:
            context["created_credentials"] = credential_notice
            del self.request.session["staff_created_credentials"]
            self.request.session.modified = True
        context["must_change_password"] = (
            bool(self.object.user_id)
            and hasattr(self.object.user, "security_profile")
            and self.object.user.security_profile.must_change_password
        )
        if self.object.role == Staff.Role.DOCTOR:
            schedules = self.object.doctor_schedules.select_related("shift").order_by("-work_date", "shift__start_time")
            appointments = Appointment.objects.select_related(
                "patient",
                "doctor_schedule__shift",
                "service",
            ).filter(doctor_schedule__doctor=self.object).order_by("-doctor_schedule__work_date", "-start_time")
            context["doctor_schedules"] = schedules[:10]
            context["appointments"] = appointments[:10]
        return context


class StaffCreateView(StaffRequiredMixin, CreateView):
    model = Staff
    form_class = StaffForm
    template_name = "clinic/staff_form.html"

    def get_success_url(self):
        return reverse("clinic:staff-detail", kwargs={"pk": self.object.pk})

    def form_valid(self, form):
        response = super().form_valid(form)
        if form.generated_user:
            self.request.session["staff_created_credentials"] = {
                "staff_id": self.object.pk,
                "username": form.generated_username,
                "password": form.generated_password,
            }
            messages.warning(
                self.request,
                "Đã tạo hồ sơ và tài khoản đăng nhập. Mật khẩu khởi tạo chỉ hiển thị một lần ở trang chi tiết.",
            )
        else:
            messages.success(self.request, "Đã tạo hồ sơ nhân viên/bác sĩ.")
        return response


class StaffUpdateView(StaffRequiredMixin, UpdateView):
    model = Staff
    form_class = StaffForm
    template_name = "clinic/staff_form.html"

    def get_success_url(self):
        return reverse("clinic:staff-detail", kwargs={"pk": self.object.pk})

    def form_valid(self, form):
        response = super().form_valid(form)
        if form.generated_user:
            self.request.session["staff_created_credentials"] = {
                "staff_id": self.object.pk,
                "username": form.generated_username,
                "password": form.generated_password,
            }
            messages.warning(
                self.request,
                "Đã tạo tài khoản đăng nhập cho hồ sơ này. Mật khẩu khởi tạo chỉ hiển thị một lần ở trang chi tiết.",
            )
        else:
            messages.success(self.request, "Đã cập nhật hồ sơ nhân viên/bác sĩ.")
        return response


class StaffDeleteView(StaffRequiredMixin, DeleteView):
    model = Staff
    template_name = "clinic/staff_confirm_delete.html"
    success_url = reverse_lazy("clinic:staff-list")

    def form_valid(self, form):
        staff = self.get_object()
        if staff.user_id and staff.user.is_active:
            staff.user.is_active = False
            staff.user.save(update_fields=["is_active"])
        messages.success(self.request, "Đã xóa hồ sơ nhân viên/bác sĩ.")
        return super().form_valid(form)


class ServiceCategoryListView(StaffRequiredMixin, ListView):
    model = ServiceCategory
    template_name = "clinic/service_category_list.html"
    context_object_name = "categories"
    paginate_by = LIST_PAGE_SIZE

    def get_queryset(self):
        queryset = ServiceCategory.objects.annotate(service_count=Count("services")).order_by("name")
        keyword = self.request.GET.get("q", "").strip()
        status = self.request.GET.get("status", "").strip()
        if keyword:
            queryset = queryset.filter(
                Q(code__icontains=keyword)
                | Q(name__icontains=keyword)
                | Q(description__icontains=keyword)
            )
        if status == "active":
            queryset = queryset.filter(is_active=True)
        elif status == "inactive":
            queryset = queryset.filter(is_active=False)
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["keyword"] = self.request.GET.get("q", "").strip()
        context["selected_status"] = self.request.GET.get("status", "").strip()
        context["pagination_query"] = get_pagination_query(self.request)
        return context


class ServiceCategoryDetailView(StaffRequiredMixin, DetailView):
    model = ServiceCategory
    template_name = "clinic/service_category_detail.html"
    context_object_name = "category"

    def get_queryset(self):
        return ServiceCategory.objects.annotate(service_count=Count("services"))

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        current_price_qs = get_current_service_price_subquery()
        context["services"] = (
            self.object.services.select_related("category").annotate(
                current_price=Subquery(current_price_qs.values("price")[:1]),
                current_price_list=Subquery(current_price_qs.values("price_list__name")[:1]),
            )
            .order_by("name")
        )
        return context


class ServiceCategoryCreateView(StaffRequiredMixin, CreateView):
    model = ServiceCategory
    form_class = ServiceCategoryForm
    template_name = "clinic/service_category_form.html"

    def get_success_url(self):
        return reverse("clinic:service-category-detail", kwargs={"pk": self.object.pk})

    def form_valid(self, form):
        messages.success(self.request, "Đã tạo danh mục dịch vụ.")
        return super().form_valid(form)


class ServiceCategoryUpdateView(StaffRequiredMixin, UpdateView):
    model = ServiceCategory
    form_class = ServiceCategoryForm
    template_name = "clinic/service_category_form.html"

    def get_success_url(self):
        return reverse("clinic:service-category-detail", kwargs={"pk": self.object.pk})

    def form_valid(self, form):
        messages.success(self.request, "Đã cập nhật danh mục dịch vụ.")
        return super().form_valid(form)


class ServiceCategoryDeleteView(StaffRequiredMixin, DeleteView):
    model = ServiceCategory
    template_name = "clinic/service_category_confirm_delete.html"
    success_url = reverse_lazy("clinic:service-category-list")

    def form_valid(self, form):
        messages.success(self.request, "Đã xóa danh mục dịch vụ.")
        return super().form_valid(form)


class ServiceListView(StaffRequiredMixin, ListView):
    model = Service
    template_name = "clinic/service_list.html"
    context_object_name = "services"
    paginate_by = LIST_PAGE_SIZE

    def get_queryset(self):
        current_price_qs = get_current_service_price_subquery()
        queryset = (
            Service.objects.select_related("category")
            .annotate(
                current_price=Subquery(current_price_qs.values("price")[:1]),
                current_price_list=Subquery(current_price_qs.values("price_list__name")[:1]),
            )
            .order_by("category__name", "name")
        )
        keyword = self.request.GET.get("q", "").strip()
        category_id = self.request.GET.get("category", "").strip()
        status = self.request.GET.get("status", "").strip()
        price_status = self.request.GET.get("price_status", "").strip()
        if keyword:
            queryset = queryset.filter(
                Q(code__icontains=keyword)
                | Q(name__icontains=keyword)
                | Q(description__icontains=keyword)
                | Q(category__name__icontains=keyword)
            )
        if category_id:
            queryset = queryset.filter(category_id=category_id)
        if status == "active":
            queryset = queryset.filter(is_active=True)
        elif status == "inactive":
            queryset = queryset.filter(is_active=False)
        if price_status == "priced":
            queryset = queryset.filter(current_price__isnull=False)
        elif price_status == "missing":
            queryset = queryset.filter(current_price__isnull=True)
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["keyword"] = self.request.GET.get("q", "").strip()
        context["selected_category"] = self.request.GET.get("category", "").strip()
        context["selected_status"] = self.request.GET.get("status", "").strip()
        context["selected_price_status"] = self.request.GET.get("price_status", "").strip()
        context["categories"] = ServiceCategory.objects.filter(is_active=True).order_by("name")
        context["pagination_query"] = get_pagination_query(self.request)
        return context


class ServiceDetailView(StaffRequiredMixin, DetailView):
    model = Service
    template_name = "clinic/service_detail.html"
    context_object_name = "service"

    def get_queryset(self):
        current_price_qs = get_current_service_price_subquery()
        return Service.objects.select_related("category").annotate(
            current_price=Subquery(current_price_qs.values("price")[:1]),
            current_price_list=Subquery(current_price_qs.values("price_list__name")[:1]),
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["price_history"] = self.object.prices.select_related("price_list").order_by(
            "-price_list__effective_from",
            "price",
        )
        context["recent_appointments"] = (
            self.object.appointments.select_related(
                "patient",
                "doctor_schedule__doctor",
                "doctor_schedule__shift",
            )
            .order_by("-doctor_schedule__work_date", "-start_time")[:10]
        )
        return context


class ServiceCreateView(StaffRequiredMixin, CreateView):
    model = Service
    form_class = ServiceForm
    template_name = "clinic/service_form.html"

    def get_success_url(self):
        return reverse("clinic:service-detail", kwargs={"pk": self.object.pk})

    def form_valid(self, form):
        messages.success(self.request, "Đã tạo dịch vụ.")
        return super().form_valid(form)


class ServiceUpdateView(StaffRequiredMixin, UpdateView):
    model = Service
    form_class = ServiceForm
    template_name = "clinic/service_form.html"

    def get_success_url(self):
        return reverse("clinic:service-detail", kwargs={"pk": self.object.pk})

    def form_valid(self, form):
        messages.success(self.request, "Đã cập nhật dịch vụ.")
        return super().form_valid(form)


class ServiceDeleteView(StaffRequiredMixin, DeleteView):
    model = Service
    template_name = "clinic/service_confirm_delete.html"
    success_url = reverse_lazy("clinic:service-list")

    def form_valid(self, form):
        messages.success(self.request, "Đã xóa dịch vụ.")
        return super().form_valid(form)


class PriceListListView(StaffRequiredMixin, ListView):
    model = PriceList
    template_name = "clinic/price_list_list.html"
    context_object_name = "price_lists"
    paginate_by = LIST_PAGE_SIZE

    def get_queryset(self):
        queryset = PriceList.objects.annotate(price_count=Count("prices")).order_by("-effective_from", "name")
        keyword = self.request.GET.get("q", "").strip()
        status = self.request.GET.get("status", "").strip()
        apply_status = self.request.GET.get("apply_status", "").strip()
        today = timezone.localdate()
        if keyword:
            queryset = queryset.filter(Q(name__icontains=keyword) | Q(note__icontains=keyword))
        if status == "active":
            queryset = queryset.filter(is_active=True)
        elif status == "inactive":
            queryset = queryset.filter(is_active=False)
        if apply_status == "current":
            queryset = queryset.filter(effective_from__lte=today).filter(
                Q(effective_to__isnull=True) | Q(effective_to__gte=today)
            )
        elif apply_status == "upcoming":
            queryset = queryset.filter(effective_from__gt=today)
        elif apply_status == "expired":
            queryset = queryset.filter(effective_to__lt=today)
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["keyword"] = self.request.GET.get("q", "").strip()
        context["selected_status"] = self.request.GET.get("status", "").strip()
        context["selected_apply_status"] = self.request.GET.get("apply_status", "").strip()
        context["pagination_query"] = get_pagination_query(self.request)
        return context


class PriceListDetailView(StaffRequiredMixin, DetailView):
    model = PriceList
    template_name = "clinic/price_list_detail.html"
    context_object_name = "price_list"

    def get_queryset(self):
        return PriceList.objects.prefetch_related("prices__service__category")


class PriceListCreateView(StaffRequiredMixin, CreateView):
    model = PriceList
    form_class = PriceListForm
    template_name = "clinic/price_list_form.html"

    def get_success_url(self):
        return reverse("clinic:price-list-detail", kwargs={"pk": self.object.pk})

    def form_valid(self, form):
        messages.success(self.request, "Đã tạo bảng giá dịch vụ.")
        return super().form_valid(form)


class PriceListUpdateView(StaffRequiredMixin, UpdateView):
    model = PriceList
    form_class = PriceListForm
    template_name = "clinic/price_list_form.html"

    def get_success_url(self):
        return reverse("clinic:price-list-detail", kwargs={"pk": self.object.pk})

    def form_valid(self, form):
        messages.success(self.request, "Đã cập nhật bảng giá dịch vụ.")
        return super().form_valid(form)


class PriceListDeleteView(StaffRequiredMixin, DeleteView):
    model = PriceList
    template_name = "clinic/price_list_confirm_delete.html"
    success_url = reverse_lazy("clinic:price-list-list")

    def form_valid(self, form):
        messages.success(self.request, "Đã xóa bảng giá dịch vụ.")
        return super().form_valid(form)


class ServicePriceCreateView(StaffRequiredMixin, CreateView):
    model = ServicePrice
    form_class = ServicePriceForm
    template_name = "clinic/service_price_form.html"

    def dispatch(self, request, *args, **kwargs):
        self.price_list = get_object_or_404(PriceList, pk=kwargs["price_list_pk"])
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["price_list"] = self.price_list
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["price_list"] = self.price_list
        return context

    def get_success_url(self):
        return reverse("clinic:price-list-detail", kwargs={"pk": self.price_list.pk})

    def form_valid(self, form):
        form.instance.price_list = self.price_list
        messages.success(self.request, "Đã thêm giá dịch vụ.")
        return super().form_valid(form)


class ServicePriceUpdateView(StaffRequiredMixin, UpdateView):
    model = ServicePrice
    form_class = ServicePriceForm
    template_name = "clinic/service_price_form.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["price_list"] = self.object.price_list
        return context

    def get_success_url(self):
        return reverse("clinic:price-list-detail", kwargs={"pk": self.object.price_list_id})

    def form_valid(self, form):
        messages.success(self.request, "Đã cập nhật giá dịch vụ.")
        return super().form_valid(form)


class ServicePriceDeleteView(StaffRequiredMixin, DeleteView):
    model = ServicePrice
    template_name = "clinic/service_price_confirm_delete.html"

    def get_success_url(self):
        return reverse("clinic:price-list-detail", kwargs={"pk": self.object.price_list_id})

    def form_valid(self, form):
        messages.success(self.request, "Đã xóa giá dịch vụ.")
        return super().form_valid(form)


class InvoiceListView(StaffRequiredMixin, ListView):
    model = Invoice
    template_name = "clinic/invoice_list.html"
    context_object_name = "invoices"
    paginate_by = LIST_PAGE_SIZE

    def get_queryset(self):
        queryset = Invoice.objects.select_related(
            "patient",
            "appointment",
        ).annotate(item_count=Count("items")).order_by("-issue_date", "-id")
        keyword = self.request.GET.get("q", "").strip()
        status = self.request.GET.get("status", "").strip()
        payment_type = self.request.GET.get("payment_type", "").strip()
        date_from = self.request.GET.get("date_from", "").strip()
        date_to = self.request.GET.get("date_to", "").strip()

        if keyword:
            queryset = queryset.filter(
                Q(invoice_code__icontains=keyword)
                | Q(patient__patient_code__icontains=keyword)
                | Q(patient__full_name__icontains=keyword)
                | Q(patient__phone__icontains=keyword)
                | Q(note__icontains=keyword)
            )
        if status:
            queryset = queryset.filter(status=status)
        if payment_type:
            queryset = queryset.filter(payment_type=payment_type)
        if date_from:
            queryset = queryset.filter(issue_date__gte=date_from)
        if date_to:
            queryset = queryset.filter(issue_date__lte=date_to)
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["keyword"] = self.request.GET.get("q", "").strip()
        context["selected_status"] = self.request.GET.get("status", "").strip()
        context["selected_payment_type"] = self.request.GET.get("payment_type", "").strip()
        context["selected_date_from"] = self.request.GET.get("date_from", "").strip()
        context["selected_date_to"] = self.request.GET.get("date_to", "").strip()
        context["status_choices"] = Invoice.Status.choices
        context["payment_type_choices"] = Invoice.PaymentType.choices
        context["pagination_query"] = get_pagination_query(self.request)
        return context


class InvoiceDetailView(StaffRequiredMixin, DetailView):
    model = Invoice
    template_name = "clinic/invoice_detail.html"
    context_object_name = "invoice"

    def get_queryset(self):
        return Invoice.objects.select_related("patient", "appointment").prefetch_related(
            "items__service",
            "payments",
            "payment_transactions__payment",
        )


class InvoiceCreateView(StaffRequiredMixin, CreateView):
    model = Invoice
    form_class = InvoiceForm
    template_name = "clinic/invoice_form.html"

    def get_initial(self):
        initial = super().get_initial()
        appointment_id = self.request.GET.get("appointment", "").strip()
        patient_id = self.request.GET.get("patient", "").strip()

        if appointment_id.isdigit():
            appointment = Appointment.objects.select_related("patient").filter(pk=appointment_id).first()
            if appointment:
                initial["appointment"] = appointment
                initial["patient"] = appointment.patient
        elif patient_id.isdigit():
            patient = Patient.objects.filter(pk=patient_id).first()
            if patient:
                initial["patient"] = patient
        return initial

    def get_success_url(self):
        return reverse("clinic:invoice-detail", kwargs={"pk": self.object.pk})

    def form_valid(self, form):
        response = super().form_valid(form)
        appointment = self.object.appointment
        if appointment and appointment.service and not self.object.items.exists():
            service_price = get_current_service_price(appointment.service)
            if service_price:
                InvoiceItem.objects.create(
                    invoice=self.object,
                    service=appointment.service,
                    quantity=1,
                    unit_price=service_price.price,
                )
            else:
                messages.warning(
                    self.request,
                    "Lịch khám đã được liên kết nhưng dịch vụ chưa có giá hiện hành. Hãy thêm chi phí thủ công.",
                )
        messages.success(self.request, "Đã tạo hóa đơn.")
        return response


class InvoiceUpdateView(StaffRequiredMixin, UpdateView):
    model = Invoice
    form_class = InvoiceForm
    template_name = "clinic/invoice_form.html"

    def get_success_url(self):
        return reverse("clinic:invoice-detail", kwargs={"pk": self.object.pk})

    def form_valid(self, form):
        messages.success(self.request, "Đã cập nhật hóa đơn.")
        return super().form_valid(form)


class InvoiceDeleteView(StaffRequiredMixin, DeleteView):
    model = Invoice
    template_name = "clinic/invoice_confirm_delete.html"
    success_url = reverse_lazy("clinic:invoice-list")

    def form_valid(self, form):
        messages.success(self.request, "Đã xóa hóa đơn.")
        return super().form_valid(form)


class InvoicePDFView(StaffRequiredMixin, DetailView):
    model = Invoice

    def get_queryset(self):
        return Invoice.objects.select_related("patient", "appointment").prefetch_related(
            "items__service",
            "payments",
        )

    def get(self, request, *args, **kwargs):
        invoice = self.get_object()
        response = HttpResponse(build_invoice_pdf(invoice), content_type="application/pdf")
        response["Content-Disposition"] = f'inline; filename="{invoice.invoice_code}.pdf"'
        return response


class AppointmentTicketPDFView(StaffRequiredMixin, DetailView):
    model = Appointment
    permission_required = "clinic.view_appointment"

    def get_queryset(self):
        queryset = Appointment.objects.select_related(
            "patient",
            "doctor_schedule__doctor",
            "doctor_schedule__shift",
            "checked_in_by",
        )
        return doctor_scoped_appointments(queryset, self.request.user)

    def get(self, request, *args, **kwargs):
        appointment = self.get_object()
        response = HttpResponse(build_appointment_ticket_pdf(appointment), content_type="application/pdf")
        response["Content-Disposition"] = f'inline; filename="{appointment.appointment_code}-ticket.pdf"'
        return response


class InvoiceItemCreateView(StaffRequiredMixin, CreateView):
    model = InvoiceItem
    form_class = InvoiceItemForm
    template_name = "clinic/invoice_item_form.html"

    def dispatch(self, request, *args, **kwargs):
        self.invoice = get_object_or_404(Invoice, pk=kwargs["invoice_pk"])
        return super().dispatch(request, *args, **kwargs)

    def get_initial(self):
        initial = super().get_initial()
        service_id = self.request.GET.get("service", "").strip()
        if service_id.isdigit():
            service = Service.objects.filter(pk=service_id, is_active=True).first()
            if service:
                initial["service"] = service
                service_price = get_current_service_price(service)
                if service_price:
                    initial["unit_price"] = service_price.price
        return initial

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["invoice"] = self.invoice
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["invoice"] = self.invoice
        return context

    def get_success_url(self):
        return reverse("clinic:invoice-detail", kwargs={"pk": self.invoice.pk})

    def form_valid(self, form):
        form.instance.invoice = self.invoice
        messages.success(self.request, "Đã thêm chi phí điều trị vào hóa đơn.")
        return super().form_valid(form)


class InvoiceItemUpdateView(StaffRequiredMixin, UpdateView):
    model = InvoiceItem
    form_class = InvoiceItemForm
    template_name = "clinic/invoice_item_form.html"

    def get_queryset(self):
        return InvoiceItem.objects.select_related("invoice", "service")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["invoice"] = self.object.invoice
        return context

    def get_success_url(self):
        return reverse("clinic:invoice-detail", kwargs={"pk": self.object.invoice_id})

    def form_valid(self, form):
        messages.success(self.request, "Đã cập nhật chi phí điều trị.")
        return super().form_valid(form)


class InvoiceItemDeleteView(StaffRequiredMixin, DeleteView):
    model = InvoiceItem
    template_name = "clinic/invoice_item_confirm_delete.html"

    def get_success_url(self):
        return reverse("clinic:invoice-detail", kwargs={"pk": self.object.invoice_id})

    def form_valid(self, form):
        messages.success(self.request, "Đã xóa chi phí điều trị.")
        return super().form_valid(form)


class PaymentCreateView(StaffRequiredMixin, CreateView):
    model = Payment
    form_class = PaymentForm
    template_name = "clinic/payment_form.html"

    def dispatch(self, request, *args, **kwargs):
        self.invoice = get_object_or_404(Invoice, pk=kwargs["invoice_pk"])
        if request.method.lower() == "get" and self.invoice.outstanding_amount <= 0:
            messages.warning(self.request, "Hóa đơn không còn số tiền cần thanh toán.")
            return redirect("clinic:invoice-detail", pk=self.invoice.pk)
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["invoice"] = self.invoice
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["invoice"] = self.invoice
        return context

    def get_success_url(self):
        return reverse("clinic:invoice-detail", kwargs={"pk": self.invoice.pk})

    def form_valid(self, form):
        form.instance.invoice = self.invoice
        messages.success(self.request, "Đã ghi nhận thanh toán.")
        return super().form_valid(form)


class PaymentUpdateView(StaffRequiredMixin, UpdateView):
    model = Payment
    form_class = PaymentForm
    template_name = "clinic/payment_form.html"

    def get_queryset(self):
        return Payment.objects.select_related("invoice")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["invoice"] = self.object.invoice
        return context

    def get_success_url(self):
        return reverse("clinic:invoice-detail", kwargs={"pk": self.object.invoice_id})

    def form_valid(self, form):
        messages.success(self.request, "Đã cập nhật thanh toán.")
        return super().form_valid(form)


class PaymentDeleteView(StaffRequiredMixin, DeleteView):
    model = Payment
    template_name = "clinic/payment_confirm_delete.html"

    def get_success_url(self):
        return reverse("clinic:invoice-detail", kwargs={"pk": self.object.invoice_id})

    def form_valid(self, form):
        messages.success(self.request, "Đã xóa thanh toán.")
        return super().form_valid(form)


class MoMoPaymentCreateView(StaffRequiredMixin, FormView):
    form_class = MoMoPaymentForm
    template_name = "clinic/momo_payment_form.html"
    permission_required = "clinic.add_paymenttransaction"

    def dispatch(self, request, *args, **kwargs):
        self.invoice = get_object_or_404(Invoice.objects.select_related("patient"), pk=kwargs["invoice_pk"])
        if self.invoice.outstanding_amount <= 0:
            messages.warning(request, "Hóa đơn không còn số tiền cần thanh toán.")
            return redirect("clinic:invoice-detail", pk=self.invoice.pk)
        if not is_momo_configured():
            messages.error(request, "Chưa cấu hình MoMo trong môi trường vận hành.")
            return redirect("clinic:invoice-detail", pk=self.invoice.pk)
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["invoice"] = self.invoice
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["invoice"] = self.invoice
        return context

    def form_valid(self, form):
        payment_transaction = PaymentTransaction.objects.create(
            invoice=self.invoice,
            provider=PaymentTransaction.Provider.MOMO,
            amount=form.cleaned_data["amount"],
            customer_email=form.cleaned_data.get("customer_email", ""),
            order_id=f"INV{self.invoice.pk}_{uuid4().hex[:18]}",
            request_id=f"REQ{uuid4().hex[:22]}",
        )
        try:
            response_data = create_momo_transaction(payment_transaction, self.request)
        except urllib_error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="ignore")
            payment_transaction.status = PaymentTransaction.Status.FAILED
            payment_transaction.provider_message = body[:255] or str(exc)
            payment_transaction.save(update_fields=["status", "provider_message", "updated_at"])
            messages.error(self.request, "MoMo từ chối tạo giao dịch. Kiểm tra lại cấu hình hoặc dữ liệu gửi đi.")
            return redirect("clinic:invoice-detail", pk=self.invoice.pk)
        except Exception as exc:
            payment_transaction.status = PaymentTransaction.Status.FAILED
            payment_transaction.provider_message = str(exc)[:255]
            payment_transaction.save(update_fields=["status", "provider_message", "updated_at"])
            messages.error(self.request, "Không thể tạo giao dịch MoMo ở thời điểm hiện tại.")
            return redirect("clinic:invoice-detail", pk=self.invoice.pk)

        if response_data.get("resultCode") != 0:
            messages.error(self.request, payment_transaction.provider_message or "MoMo trả về lỗi khi tạo giao dịch.")
            return redirect("clinic:invoice-detail", pk=self.invoice.pk)

        try:
            from apps.users.models import SecurityEvent

            SecurityEvent.record(
                SecurityEvent.Action.CREATE,
                request=self.request,
                target=payment_transaction,
                message="Tạo giao dịch MoMo từ hóa đơn.",
                metadata={
                    "invoice_id": self.invoice.pk,
                    "invoice_code": self.invoice.invoice_code,
                    "amount": str(payment_transaction.amount),
                },
            )
        except Exception:
            pass
        messages.success(self.request, "Đã tạo giao dịch MoMo. Mở mã QR hoặc đường dẫn để bệnh nhân thanh toán.")
        return redirect("clinic:payment-transaction-detail", pk=payment_transaction.pk)


class PaymentTransactionDetailView(StaffRequiredMixin, DetailView):
    model = PaymentTransaction
    template_name = "clinic/payment_transaction_detail.html"
    context_object_name = "payment_transaction"

    def get_queryset(self):
        return PaymentTransaction.objects.select_related("invoice__patient", "payment")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["invoice"] = self.object.invoice
        context["qr_svg"] = build_qr_svg(self.object.qr_code_url or self.object.pay_url)
        return context


class PaymentTransactionQueryView(StaffRequiredMixin, View):
    permission_required = "clinic.change_paymenttransaction"

    def post(self, request, pk):
        payment_transaction = get_object_or_404(PaymentTransaction.objects.select_related("invoice"), pk=pk)
        try:
            response_data = query_momo_transaction(payment_transaction)
            apply_momo_transaction_result(payment_transaction, response_data, request=request)
        except Exception:
            messages.error(request, "Không thể truy vấn trạng thái giao dịch từ MoMo.")
            return redirect("clinic:payment-transaction-detail", pk=payment_transaction.pk)

        payment_transaction.refresh_from_db()
        if payment_transaction.status == PaymentTransaction.Status.SUCCESS:
            messages.success(request, "MoMo đã xác nhận giao dịch thành công.")
        elif payment_transaction.status == PaymentTransaction.Status.FAILED:
            messages.warning(request, payment_transaction.provider_message or "Giao dịch chưa thành công.")
        else:
            messages.warning(request, "Giao dịch vẫn đang chờ MoMo xác nhận.")
        try:
            from apps.users.models import SecurityEvent

            SecurityEvent.record(
                SecurityEvent.Action.UPDATE,
                request=request,
                target=payment_transaction,
                message="Nhân viên truy vấn trạng thái giao dịch MoMo.",
                metadata={"status": payment_transaction.status, "result_code": payment_transaction.result_code},
            )
        except Exception:
            pass
        return redirect("clinic:payment-transaction-detail", pk=payment_transaction.pk)


class MoMoSimulationView(StaffRequiredMixin, DetailView):
    model = PaymentTransaction
    template_name = "clinic/momo_simulate.html"
    context_object_name = "payment_transaction"
    permission_required = "clinic.change_paymenttransaction"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["invoice"] = self.object.invoice
        return context

    def post(self, request, *args, **kwargs):
        payment_transaction = self.get_object()
        action = request.POST.get("action")

        if action == "success":
            payload = {
                "partnerCode": get_momo_setting("MOMO_PARTNER_CODE", "MOMO"),
                "orderId": payment_transaction.order_id,
                "requestId": payment_transaction.request_id,
                "amount": int(payment_transaction.amount),
                "orderInfo": f"Thanh toan hoa don {payment_transaction.invoice.invoice_code}",
                "orderType": "momo_wallet",
                "transId": f"SIM{uuid4().hex[:12]}",
                "resultCode": 0,
                "message": "Successful.",
                "payType": "qr",
                "responseTime": int(timezone.now().timestamp() * 1000),
                "extraData": "",
            }
            # Directly apply simulated successful result locally
            apply_momo_transaction_result(payment_transaction, payload, request=request)
            
            # Build return URL with successful parameters
            return_params = {
                "partnerCode": payload["partnerCode"],
                "orderId": payload["orderId"],
                "requestId": payload["requestId"],
                "amount": payload["amount"],
                "orderInfo": payload["orderInfo"],
                "orderType": payload["orderType"],
                "transId": payload["transId"],
                "resultCode": 0,
                "message": "Successful.",
                "payType": payload["payType"],
                "responseTime": payload["responseTime"],
                "extraData": payload["extraData"],
            }
            raw_signature = build_momo_ipn_signature(return_params)
            return_params["signature"] = make_momo_signature(raw_signature)
            
            return redirect(reverse("clinic:momo-return") + "?" + urlencode(return_params))

        elif action == "fail":
            payload = {
                "partnerCode": get_momo_setting("MOMO_PARTNER_CODE", "MOMO"),
                "orderId": payment_transaction.order_id,
                "requestId": payment_transaction.request_id,
                "amount": int(payment_transaction.amount),
                "orderInfo": f"Thanh toan hoa don {payment_transaction.invoice.invoice_code}",
                "orderType": "momo_wallet",
                "transId": f"SIM{uuid4().hex[:12]}",
                "resultCode": 49,
                "message": "User rejected the transaction.",
                "payType": "qr",
                "responseTime": int(timezone.now().timestamp() * 1000),
                "extraData": "",
            }
            # Directly apply simulated failed result locally
            apply_momo_transaction_result(payment_transaction, payload, request=request)
            
            # Build return URL with failed parameters
            return_params = {
                "partnerCode": payload["partnerCode"],
                "orderId": payload["orderId"],
                "requestId": payload["requestId"],
                "amount": payload["amount"],
                "orderInfo": payload["orderInfo"],
                "orderType": payload["orderType"],
                "transId": payload["transId"],
                "resultCode": 49,
                "message": "User rejected the transaction.",
                "payType": payload["payType"],
                "responseTime": payload["responseTime"],
                "extraData": payload["extraData"],
            }
            raw_signature = build_momo_ipn_signature(return_params)
            return_params["signature"] = make_momo_signature(raw_signature)
            
            return redirect(reverse("clinic:momo-return") + "?" + urlencode(return_params))

        return redirect("clinic:payment-transaction-detail", pk=payment_transaction.pk)


class MoMoReturnView(TemplateView):
    template_name = "clinic/momo_return.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        order_id = self.request.GET.get("orderId", "").strip()
        payment_transaction = PaymentTransaction.objects.select_related("invoice").filter(order_id=order_id).first()
        if payment_transaction:
            payment_transaction.redirect_payload = dict(self.request.GET.items())
            payment_transaction.save(update_fields=["redirect_payload", "updated_at"])
        context["payment_transaction"] = payment_transaction
        context["result_code"] = self.request.GET.get("resultCode", "")
        context["message"] = self.request.GET.get("message", "")
        return context


@method_decorator(csrf_exempt, name="dispatch")
class MoMoIPNView(View):
    def post(self, request, *args, **kwargs):
        try:
            payload = json.loads(request.body.decode("utf-8"))
        except Exception:
            return HttpResponse(status=204)

        if not verify_momo_ipn_signature(payload):
            return HttpResponse(status=204)

        payment_transaction = PaymentTransaction.objects.select_related("invoice").filter(order_id=payload.get("orderId")).first()
        if not payment_transaction:
            return HttpResponse(status=204)

        if (
            payload.get("partnerCode") != get_momo_setting("MOMO_PARTNER_CODE")
            or Decimal(str(payload.get("amount", "0"))) != payment_transaction.amount
        ):
            payment_transaction.status = PaymentTransaction.Status.REVIEW
            payment_transaction.raw_ipn_payload = payload
            payment_transaction.provider_message = "Du lieu IPN khong khop voi giao dich noi bo."
            payment_transaction.save(update_fields=["status", "raw_ipn_payload", "provider_message", "updated_at"])
            return HttpResponse(status=204)

        apply_momo_transaction_result(payment_transaction, payload, request=request)
        return HttpResponse(status=204)


class MedicineListView(StaffRequiredMixin, ListView):
    model = Medicine
    template_name = "clinic/medicine_list.html"
    context_object_name = "medicines"
    paginate_by = LIST_PAGE_SIZE

    def get_queryset(self):
        queryset = Medicine.objects.order_by("name", "strength")
        keyword = self.request.GET.get("q", "").strip()
        status = self.request.GET.get("status", "").strip()
        if keyword:
            queryset = queryset.filter(
                Q(medicine_code__icontains=keyword)
                | Q(name__icontains=keyword)
                | Q(active_ingredient__icontains=keyword)
                | Q(strength__icontains=keyword)
                | Q(usage_note__icontains=keyword)
            )
        if status == "active":
            queryset = queryset.filter(is_active=True)
        elif status == "inactive":
            queryset = queryset.filter(is_active=False)
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["keyword"] = self.request.GET.get("q", "").strip()
        context["selected_status"] = self.request.GET.get("status", "").strip()
        context["pagination_query"] = get_pagination_query(self.request)
        return context


class MedicineDetailView(StaffRequiredMixin, DetailView):
    model = Medicine
    template_name = "clinic/medicine_detail.html"
    context_object_name = "medicine"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        prescription_items = self.object.prescription_items.select_related(
            "prescription__patient",
            "prescription__doctor",
        )
        doctor = get_doctor_profile(self.request.user)
        if doctor:
            prescription_items = prescription_items.filter(prescription__doctor=doctor)
        context["recent_prescription_items"] = prescription_items.order_by("-prescription__prescribed_at", "-id")[:10]
        return context


class MedicineCreateView(StaffRequiredMixin, CreateView):
    model = Medicine
    form_class = MedicineForm
    template_name = "clinic/medicine_form.html"

    def get_success_url(self):
        return reverse("clinic:medicine-detail", kwargs={"pk": self.object.pk})

    def form_valid(self, form):
        messages.success(self.request, "Đã thêm thuốc.")
        return super().form_valid(form)


class MedicineUpdateView(StaffRequiredMixin, UpdateView):
    model = Medicine
    form_class = MedicineForm
    template_name = "clinic/medicine_form.html"

    def get_success_url(self):
        return reverse("clinic:medicine-detail", kwargs={"pk": self.object.pk})

    def form_valid(self, form):
        messages.success(self.request, "Đã cập nhật thuốc.")
        return super().form_valid(form)


class MedicineDeleteView(StaffRequiredMixin, DeleteView):
    model = Medicine
    template_name = "clinic/medicine_confirm_delete.html"
    success_url = reverse_lazy("clinic:medicine-list")

    def form_valid(self, form):
        messages.success(self.request, "Đã xóa thuốc.")
        return super().form_valid(form)


class SupplyListView(StaffRequiredMixin, ListView):
    model = Supply
    template_name = "clinic/supply_list.html"
    context_object_name = "supplies"
    paginate_by = LIST_PAGE_SIZE

    def get_queryset(self):
        today = timezone.localdate()
        expiry_alert_date = today + timedelta(days=30)
        queryset = (
            get_supply_stock_queryset()
            .annotate(
                lot_count=Count("lots", distinct=True),
                expired_lot_count=Count(
                    "lots",
                    filter=Q(lots__current_quantity__gt=0, lots__expiry_date__lt=today),
                    distinct=True,
                ),
                expiring_lot_count=Count(
                    "lots",
                    filter=Q(
                        lots__current_quantity__gt=0,
                        lots__expiry_date__gte=today,
                        lots__expiry_date__lte=expiry_alert_date,
                    ),
                    distinct=True,
                ),
            )
            .order_by("category", "name")
        )
        keyword = self.request.GET.get("q", "").strip()
        category = self.request.GET.get("category", "").strip()
        status = self.request.GET.get("status", "").strip()
        stock_status = self.request.GET.get("stock_status", "").strip()
        expiry_status = self.request.GET.get("expiry_status", "").strip()

        if keyword:
            queryset = queryset.filter(
                Q(supply_code__icontains=keyword)
                | Q(name__icontains=keyword)
                | Q(unit__icontains=keyword)
                | Q(description__icontains=keyword)
                | Q(lots__lot_number__icontains=keyword)
                | Q(lots__supplier__icontains=keyword)
            )
        if category:
            queryset = queryset.filter(category=category)
        if status == "active":
            queryset = queryset.filter(is_active=True)
        elif status == "inactive":
            queryset = queryset.filter(is_active=False)
        if stock_status == "out":
            queryset = queryset.filter(stock_quantity__lte=0)
        elif stock_status == "low":
            queryset = queryset.filter(minimum_quantity__gt=0, stock_quantity__lte=F("minimum_quantity"))
        elif stock_status == "available":
            queryset = queryset.filter(stock_quantity__gt=0)
        if expiry_status == "expired":
            queryset = queryset.filter(expired_lot_count__gt=0)
        elif expiry_status == "expiring":
            queryset = queryset.filter(expiring_lot_count__gt=0)
        return queryset.distinct()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        today = timezone.localdate()
        context["keyword"] = self.request.GET.get("q", "").strip()
        context["selected_category"] = self.request.GET.get("category", "").strip()
        context["selected_status"] = self.request.GET.get("status", "").strip()
        context["selected_stock_status"] = self.request.GET.get("stock_status", "").strip()
        context["selected_expiry_status"] = self.request.GET.get("expiry_status", "").strip()
        context["category_choices"] = Supply.Category.choices
        context["pagination_query"] = get_pagination_query(self.request)
        context["total_supply_count"] = Supply.objects.count()
        context["low_stock_count"] = (
            get_supply_stock_queryset()
            .filter(is_active=True, minimum_quantity__gt=0, stock_quantity__lte=F("minimum_quantity"))
            .count()
        )
        context["expired_lot_count"] = SupplyLot.objects.filter(
            current_quantity__gt=0,
            expiry_date__lt=today,
        ).count()
        context["expiring_lot_count"] = SupplyLot.objects.filter(
            current_quantity__gt=0,
            expiry_date__gte=today,
            expiry_date__lte=today + timedelta(days=30),
        ).count()
        return context


class SupplyDetailView(StaffRequiredMixin, DetailView):
    model = Supply
    template_name = "clinic/supply_detail.html"
    context_object_name = "supply"

    def get_queryset(self):
        today = timezone.localdate()
        return get_supply_stock_queryset().annotate(
            expired_lot_count=Count(
                "lots",
                filter=Q(lots__current_quantity__gt=0, lots__expiry_date__lt=today),
                distinct=True,
            ),
            expiring_lot_count=Count(
                "lots",
                filter=Q(
                    lots__current_quantity__gt=0,
                    lots__expiry_date__gte=today,
                    lots__expiry_date__lte=today + timedelta(days=30),
                ),
                distinct=True,
            ),
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["lots"] = self.object.lots.order_by("expiry_date", "received_date", "id")
        context["recent_exports"] = SupplyExport.objects.select_related("lot", "performed_by").filter(
            lot__supply=self.object,
        )[:10]
        return context


class SupplyCreateView(StaffRequiredMixin, CreateView):
    model = Supply
    form_class = SupplyForm
    template_name = "clinic/supply_form.html"

    def get_success_url(self):
        return reverse("clinic:supply-detail", kwargs={"pk": self.object.pk})

    def form_valid(self, form):
        messages.success(self.request, "Đã thêm vật tư.")
        return super().form_valid(form)


class SupplyUpdateView(StaffRequiredMixin, UpdateView):
    model = Supply
    form_class = SupplyForm
    template_name = "clinic/supply_form.html"

    def get_success_url(self):
        return reverse("clinic:supply-detail", kwargs={"pk": self.object.pk})

    def form_valid(self, form):
        messages.success(self.request, "Đã cập nhật vật tư.")
        return super().form_valid(form)


class SupplyDeleteView(StaffRequiredMixin, DeleteView):
    model = Supply
    template_name = "clinic/supply_confirm_delete.html"
    success_url = reverse_lazy("clinic:supply-list")

    def form_valid(self, form):
        messages.success(self.request, "Đã xóa vật tư.")
        return super().form_valid(form)


class SupplyLotCreateView(StaffRequiredMixin, CreateView):
    model = SupplyLot
    form_class = SupplyLotForm
    template_name = "clinic/supply_lot_form.html"

    def dispatch(self, request, *args, **kwargs):
        self.supply = get_object_or_404(Supply, pk=kwargs["supply_pk"])
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["supply"] = self.supply
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["supply"] = self.supply
        return context

    def get_success_url(self):
        return reverse("clinic:supply-detail", kwargs={"pk": self.supply.pk})

    def form_valid(self, form):
        form.instance.supply = self.supply
        messages.success(self.request, "Đã nhập lô vật tư vào kho.")
        return super().form_valid(form)


class SupplyLotUpdateView(StaffRequiredMixin, UpdateView):
    model = SupplyLot
    form_class = SupplyLotForm
    template_name = "clinic/supply_lot_form.html"

    def get_queryset(self):
        return SupplyLot.objects.select_related("supply")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["supply"] = self.object.supply
        return context

    def get_success_url(self):
        return reverse("clinic:supply-detail", kwargs={"pk": self.object.supply_id})

    def form_valid(self, form):
        messages.success(self.request, "Đã cập nhật lô vật tư.")
        return super().form_valid(form)


class SupplyLotDeleteView(StaffRequiredMixin, DeleteView):
    model = SupplyLot
    template_name = "clinic/supply_lot_confirm_delete.html"

    def get_queryset(self):
        return SupplyLot.objects.select_related("supply")

    def get_success_url(self):
        return reverse("clinic:supply-detail", kwargs={"pk": self.object.supply_id})

    def form_valid(self, form):
        messages.success(self.request, "Đã xóa lô vật tư.")
        return super().form_valid(form)


class SupplyExportCreateView(StaffRequiredMixin, CreateView):
    model = SupplyExport
    form_class = SupplyExportForm
    template_name = "clinic/supply_export_form.html"

    def dispatch(self, request, *args, **kwargs):
        self.supply = get_object_or_404(Supply, pk=kwargs["supply_pk"])
        return super().dispatch(request, *args, **kwargs)

    def get_initial(self):
        initial = super().get_initial()
        lot_id = self.request.GET.get("lot", "").strip()
        if lot_id.isdigit():
            lot = SupplyLot.objects.filter(pk=lot_id, supply=self.supply).first()
            if lot:
                initial["lot"] = lot
        return initial

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["supply"] = self.supply
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["supply"] = self.supply
        return context

    def get_success_url(self):
        return reverse("clinic:supply-detail", kwargs={"pk": self.supply.pk})

    def form_valid(self, form):
        messages.success(self.request, "Đã xuất vật tư khỏi kho.")
        return super().form_valid(form)


class SupplyExportUpdateView(StaffRequiredMixin, UpdateView):
    model = SupplyExport
    form_class = SupplyExportForm
    template_name = "clinic/supply_export_form.html"

    def get_queryset(self):
        return SupplyExport.objects.select_related("lot__supply", "performed_by")

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["supply"] = self.object.supply
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["supply"] = self.object.supply
        return context

    def get_success_url(self):
        return reverse("clinic:supply-detail", kwargs={"pk": self.object.supply.pk})

    def form_valid(self, form):
        messages.success(self.request, "Đã cập nhật phiếu xuất vật tư.")
        return super().form_valid(form)


class SupplyExportDeleteView(StaffRequiredMixin, DeleteView):
    model = SupplyExport
    template_name = "clinic/supply_export_confirm_delete.html"

    def get_queryset(self):
        return SupplyExport.objects.select_related("lot__supply", "performed_by")

    def get_success_url(self):
        return reverse("clinic:supply-detail", kwargs={"pk": self.object.supply.pk})

    def form_valid(self, form):
        messages.success(self.request, "Đã xóa phiếu xuất vật tư và hoàn lại tồn kho.")
        return super().form_valid(form)


class PrescriptionListView(StaffRequiredMixin, ListView):
    model = Prescription
    template_name = "clinic/prescription_list.html"
    context_object_name = "prescriptions"
    paginate_by = LIST_PAGE_SIZE

    def get_queryset(self):
        queryset = doctor_scoped_prescriptions(Prescription.objects.select_related("patient", "doctor", "appointment"), self.request.user).annotate(
            item_count=Count("items")
        ).order_by("-prescribed_at", "-id")
        keyword = self.request.GET.get("q", "").strip()
        patient_id = self.request.GET.get("patient", "").strip()
        doctor_id = self.request.GET.get("doctor", "").strip()
        date_from = self.request.GET.get("date_from", "").strip()
        date_to = self.request.GET.get("date_to", "").strip()

        if keyword:
            queryset = queryset.filter(
                Q(prescription_code__icontains=keyword)
                | Q(patient__patient_code__icontains=keyword)
                | Q(patient__full_name__icontains=keyword)
                | Q(patient__phone__icontains=keyword)
                | Q(diagnosis__icontains=keyword)
                | Q(note__icontains=keyword)
            )
        if patient_id:
            queryset = queryset.filter(patient_id=patient_id)
        if doctor_id:
            queryset = queryset.filter(doctor_id=doctor_id)
        if date_from:
            queryset = queryset.filter(prescribed_at__gte=date_from)
        if date_to:
            queryset = queryset.filter(prescribed_at__lte=date_to)
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["keyword"] = self.request.GET.get("q", "").strip()
        context["selected_patient"] = self.request.GET.get("patient", "").strip()
        context["selected_doctor"] = self.request.GET.get("doctor", "").strip()
        context["selected_date_from"] = self.request.GET.get("date_from", "").strip()
        context["selected_date_to"] = self.request.GET.get("date_to", "").strip()
        context["patients"] = doctor_scoped_patients(
            Patient.objects.filter(is_active=True),
            self.request.user,
        ).order_by("full_name")
        context["doctors"] = doctor_choices_for_user(self.request.user)
        context["pagination_query"] = get_pagination_query(self.request)
        return context


class PrescriptionDetailView(StaffRequiredMixin, DetailView):
    model = Prescription
    template_name = "clinic/prescription_detail.html"
    context_object_name = "prescription"

    def get_queryset(self):
        queryset = Prescription.objects.select_related("patient", "appointment", "doctor").prefetch_related(
            "items__medicine",
        )
        return doctor_scoped_prescriptions(queryset, self.request.user)


class PrescriptionCreateView(StaffRequiredMixin, CreateView):
    model = Prescription
    form_class = PrescriptionForm
    template_name = "clinic/prescription_form.html"

    def get_initial(self):
        initial = super().get_initial()
        doctor = get_doctor_profile(self.request.user)
        appointment_id = self.request.GET.get("appointment", "").strip()
        patient_id = self.request.GET.get("patient", "").strip()

        if appointment_id.isdigit():
            appointment = Appointment.objects.select_related("patient", "doctor_schedule__doctor").filter(
                pk=appointment_id
            ).first()
            if doctor and appointment and appointment.doctor_schedule.doctor_id != doctor.pk:
                appointment = None
            if appointment:
                initial["appointment"] = appointment
                initial["patient"] = appointment.patient
                initial["doctor"] = appointment.doctor_schedule.doctor
                initial["prescribed_at"] = appointment.appointment_date
                initial["diagnosis"] = appointment.chief_complaint
        elif patient_id.isdigit():
            patient = doctor_scoped_patients(Patient.objects.filter(pk=patient_id), self.request.user).first()
            if patient:
                initial["patient"] = patient
        if doctor:
            initial["doctor"] = doctor
        return initial

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["staff_user"] = self.request.user
        return kwargs

    def get_success_url(self):
        return reverse("clinic:prescription-detail", kwargs={"pk": self.object.pk})

    def form_valid(self, form):
        messages.success(self.request, "Đã tạo đơn thuốc.")
        return super().form_valid(form)


class PrescriptionUpdateView(StaffRequiredMixin, UpdateView):
    model = Prescription
    form_class = PrescriptionForm
    template_name = "clinic/prescription_form.html"

    def get_queryset(self):
        return doctor_scoped_prescriptions(super().get_queryset(), self.request.user)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["staff_user"] = self.request.user
        return kwargs

    def get_success_url(self):
        return reverse("clinic:prescription-detail", kwargs={"pk": self.object.pk})

    def form_valid(self, form):
        messages.success(self.request, "Đã cập nhật đơn thuốc.")
        return super().form_valid(form)


class PrescriptionDeleteView(StaffRequiredMixin, DeleteView):
    model = Prescription
    template_name = "clinic/prescription_confirm_delete.html"
    success_url = reverse_lazy("clinic:prescription-list")

    def get_queryset(self):
        return doctor_scoped_prescriptions(super().get_queryset(), self.request.user)

    def form_valid(self, form):
        messages.success(self.request, "Đã xóa đơn thuốc.")
        return super().form_valid(form)


class PrescriptionItemCreateView(StaffRequiredMixin, CreateView):
    model = PrescriptionItem
    form_class = PrescriptionItemForm
    template_name = "clinic/prescription_item_form.html"

    def dispatch(self, request, *args, **kwargs):
        self.prescription = get_object_or_404(
            doctor_scoped_prescriptions(Prescription.objects.all(), request.user),
            pk=kwargs["prescription_pk"],
        )
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["prescription"] = self.prescription
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["prescription"] = self.prescription
        return context

    def get_success_url(self):
        return reverse("clinic:prescription-detail", kwargs={"pk": self.prescription.pk})

    def form_valid(self, form):
        form.instance.prescription = self.prescription
        messages.success(self.request, "Đã thêm thuốc vào đơn.")
        return super().form_valid(form)


class PrescriptionItemUpdateView(StaffRequiredMixin, UpdateView):
    model = PrescriptionItem
    form_class = PrescriptionItemForm
    template_name = "clinic/prescription_item_form.html"

    def get_queryset(self):
        return PrescriptionItem.objects.select_related("prescription", "medicine").filter(
            prescription__in=doctor_scoped_prescriptions(Prescription.objects.all(), self.request.user)
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["prescription"] = self.object.prescription
        return context

    def get_success_url(self):
        return reverse("clinic:prescription-detail", kwargs={"pk": self.object.prescription_id})

    def form_valid(self, form):
        messages.success(self.request, "Đã cập nhật thuốc trong đơn.")
        return super().form_valid(form)


class PrescriptionItemDeleteView(StaffRequiredMixin, DeleteView):
    model = PrescriptionItem
    template_name = "clinic/prescription_item_confirm_delete.html"

    def get_queryset(self):
        return PrescriptionItem.objects.select_related("prescription").filter(
            prescription__in=doctor_scoped_prescriptions(Prescription.objects.all(), self.request.user)
        )

    def get_success_url(self):
        return reverse("clinic:prescription-detail", kwargs={"pk": self.object.prescription_id})

    def form_valid(self, form):
        messages.success(self.request, "Đã xóa thuốc khỏi đơn.")
        return super().form_valid(form)


class ClinicHolidayListView(StaffRequiredMixin, ListView):
    model = ClinicHoliday
    template_name = "clinic/holiday_list.html"
    context_object_name = "holidays"
    paginate_by = LIST_PAGE_SIZE

    def get_queryset(self):
        queryset = ClinicHoliday.objects.order_by("-date")
        keyword = self.request.GET.get("q", "").strip()
        status = self.request.GET.get("status", "").strip()
        if keyword:
            queryset = queryset.filter(Q(name__icontains=keyword) | Q(note__icontains=keyword))
        if status == "active":
            queryset = queryset.filter(is_active=True)
        elif status == "inactive":
            queryset = queryset.filter(is_active=False)
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["keyword"] = self.request.GET.get("q", "").strip()
        context["selected_status"] = self.request.GET.get("status", "").strip()
        context["pagination_query"] = get_pagination_query(self.request)
        return context


class ClinicHolidayCreateView(StaffRequiredMixin, CreateView):
    model = ClinicHoliday
    form_class = ClinicHolidayForm
    template_name = "clinic/holiday_form.html"
    success_url = reverse_lazy("clinic:holiday-list")

    def form_valid(self, form):
        messages.success(self.request, "Đã thiết lập ngày nghỉ.")
        return super().form_valid(form)


class ClinicHolidayUpdateView(StaffRequiredMixin, UpdateView):
    model = ClinicHoliday
    form_class = ClinicHolidayForm
    template_name = "clinic/holiday_form.html"
    success_url = reverse_lazy("clinic:holiday-list")

    def form_valid(self, form):
        messages.success(self.request, "Đã cập nhật ngày nghỉ.")
        return super().form_valid(form)


class ClinicHolidayDeleteView(StaffRequiredMixin, DeleteView):
    model = ClinicHoliday
    template_name = "clinic/holiday_confirm_delete.html"
    success_url = reverse_lazy("clinic:holiday-list")

    def form_valid(self, form):
        messages.success(self.request, "Đã xóa ngày nghỉ.")
        return super().form_valid(form)


class WorkShiftListView(StaffRequiredMixin, ListView):
    model = WorkShift
    template_name = "clinic/work_shift_list.html"
    context_object_name = "work_shifts"
    paginate_by = LIST_PAGE_SIZE

    def get_queryset(self):
        queryset = WorkShift.objects.order_by("weekday", "start_time", "name")
        weekday = self.request.GET.get("weekday", "").strip()
        status = self.request.GET.get("status", "").strip()
        if weekday != "":
            queryset = queryset.filter(weekday=weekday)
        if status == "active":
            queryset = queryset.filter(is_active=True)
        elif status == "inactive":
            queryset = queryset.filter(is_active=False)
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["weekday_choices"] = WorkShift.Weekday.choices
        context["selected_weekday"] = self.request.GET.get("weekday", "").strip()
        context["selected_status"] = self.request.GET.get("status", "").strip()
        context["pagination_query"] = get_pagination_query(self.request)
        return context


class WorkShiftCreateView(StaffRequiredMixin, CreateView):
    model = WorkShift
    form_class = WorkShiftForm
    template_name = "clinic/work_shift_form.html"
    success_url = reverse_lazy("clinic:work-shift-list")

    def form_valid(self, form):
        messages.success(self.request, "Đã thiết lập ca làm việc.")
        return super().form_valid(form)


class WorkShiftUpdateView(StaffRequiredMixin, UpdateView):
    model = WorkShift
    form_class = WorkShiftForm
    template_name = "clinic/work_shift_form.html"
    success_url = reverse_lazy("clinic:work-shift-list")

    def form_valid(self, form):
        messages.success(self.request, "Đã cập nhật ca làm việc.")
        return super().form_valid(form)


class WorkShiftDeleteView(StaffRequiredMixin, DeleteView):
    model = WorkShift
    template_name = "clinic/work_shift_confirm_delete.html"
    success_url = reverse_lazy("clinic:work-shift-list")

    def form_valid(self, form):
        messages.success(self.request, "Đã xóa ca làm việc.")
        return super().form_valid(form)


class DoctorScheduleListView(StaffRequiredMixin, ListView):
    model = DoctorSchedule
    template_name = "clinic/doctor_schedule_list.html"
    context_object_name = "doctor_schedules"
    paginate_by = LIST_PAGE_SIZE

    def get_queryset(self):
        queryset = DoctorSchedule.objects.select_related("doctor", "shift").order_by(
            "-work_date",
            "shift__start_time",
            "doctor__full_name",
        )
        doctor = get_doctor_profile(self.request.user)
        if doctor:
            queryset = queryset.filter(doctor=doctor)
        work_date = self.request.GET.get("date", "").strip()
        doctor_id = self.request.GET.get("doctor", "").strip()
        status = self.request.GET.get("status", "").strip()
        if work_date:
            queryset = queryset.filter(work_date=work_date)
        if doctor_id:
            queryset = queryset.filter(doctor_id=doctor_id)
        if status:
            queryset = queryset.filter(status=status)
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["selected_date"] = self.request.GET.get("date", "").strip()
        context["selected_doctor"] = self.request.GET.get("doctor", "").strip()
        context["selected_status"] = self.request.GET.get("status", "").strip()
        context["doctors"] = doctor_choices_for_user(self.request.user)
        context["status_choices"] = DoctorSchedule.Status.choices
        context["pagination_query"] = get_pagination_query(self.request)
        return context


class DoctorScheduleCreateView(StaffRequiredMixin, CreateView):
    model = DoctorSchedule
    form_class = DoctorScheduleForm
    template_name = "clinic/doctor_schedule_form.html"
    success_url = reverse_lazy("clinic:doctor-schedule-list")

    def form_valid(self, form):
        messages.success(self.request, "Đã đăng ký lịch trực cho bác sĩ.")
        return super().form_valid(form)


class DoctorScheduleUpdateView(StaffRequiredMixin, UpdateView):
    model = DoctorSchedule
    form_class = DoctorScheduleForm
    template_name = "clinic/doctor_schedule_form.html"
    success_url = reverse_lazy("clinic:doctor-schedule-list")

    def get_queryset(self):
        queryset = super().get_queryset()
        doctor = get_doctor_profile(self.request.user)
        if doctor:
            queryset = queryset.filter(doctor=doctor)
        return queryset

    def form_valid(self, form):
        messages.success(self.request, "Đã cập nhật lịch trực bác sĩ.")
        return super().form_valid(form)


class DoctorScheduleDeleteView(StaffRequiredMixin, DeleteView):
    model = DoctorSchedule
    template_name = "clinic/doctor_schedule_confirm_delete.html"
    success_url = reverse_lazy("clinic:doctor-schedule-list")

    def get_queryset(self):
        queryset = super().get_queryset()
        doctor = get_doctor_profile(self.request.user)
        if doctor:
            queryset = queryset.filter(doctor=doctor)
        return queryset

    def form_valid(self, form):
        messages.success(self.request, "Đã xóa lịch trực bác sĩ.")
        return super().form_valid(form)


class AppointmentListView(StaffRequiredMixin, ListView):
    model = Appointment
    template_name = "clinic/appointment_list.html"
    context_object_name = "appointments"
    paginate_by = LIST_PAGE_SIZE

    def get_queryset(self):
        queryset = doctor_scoped_appointments(Appointment.objects.select_related(
            "patient",
            "doctor_schedule__doctor",
            "doctor_schedule__shift",
            "service",
        ), self.request.user).order_by("-doctor_schedule__work_date", "start_time", "patient__full_name")
        keyword = self.request.GET.get("q", "").strip()
        date_from = self.request.GET.get("date_from", "").strip()
        date_to = self.request.GET.get("date_to", "").strip()
        doctor_id = self.request.GET.get("doctor", "").strip()
        status = self.request.GET.get("status", "").strip()

        if keyword:
            queryset = queryset.filter(
                Q(appointment_code__icontains=keyword)
                | Q(patient__patient_code__icontains=keyword)
                | Q(patient__full_name__icontains=keyword)
                | Q(patient__phone__icontains=keyword)
                | Q(chief_complaint__icontains=keyword)
            )
        if date_from:
            queryset = queryset.filter(doctor_schedule__work_date__gte=date_from)
        if date_to:
            queryset = queryset.filter(doctor_schedule__work_date__lte=date_to)
        if doctor_id:
            queryset = queryset.filter(doctor_schedule__doctor_id=doctor_id)
        if status:
            queryset = queryset.filter(status=status)
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["keyword"] = self.request.GET.get("q", "").strip()
        context["selected_date_from"] = self.request.GET.get("date_from", "").strip()
        context["selected_date_to"] = self.request.GET.get("date_to", "").strip()
        context["selected_doctor"] = self.request.GET.get("doctor", "").strip()
        context["selected_status"] = self.request.GET.get("status", "").strip()
        context["doctors"] = doctor_choices_for_user(self.request.user)
        context["status_choices"] = Appointment.Status.choices
        context["pagination_query"] = get_pagination_query(self.request)
        return context


class ReceptionTodayView(StaffRequiredMixin, TemplateView):
    template_name = "clinic/reception_today.html"
    permission_required = "clinic.view_appointment"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        today = timezone.localdate()
        all_appointments = list(self._get_today_queryset())
        appointments = list(self._get_filtered_queryset())
        self._attach_reception_alerts(all_appointments)
        self._attach_reception_alerts(appointments)
        waiting_appointments = [
            appointment for appointment in all_appointments if appointment.status == Appointment.Status.CHECKED_IN
        ]

        context.update(
            {
                "today": today,
                "appointments": appointments,
                "total_today_count": len(all_appointments),
                "scheduled_count": sum(
                    1
                    for appointment in all_appointments
                    if appointment.status in {Appointment.Status.SCHEDULED, Appointment.Status.CONFIRMED}
                ),
                "waiting_count": len(waiting_appointments),
                "walk_in_count": sum(
                    1 for appointment in all_appointments if appointment.arrival_type == Appointment.ArrivalType.WALK_IN
                ),
                "doctors": doctor_choices_for_user(self.request.user),
                "shifts": self._get_today_shifts(),
                "status_choices": Appointment.Status.choices,
                "visit_type_choices": Appointment.VisitType.choices,
                "priority_level_choices": Appointment.PriorityLevel.choices,
                "selected_keyword": self.request.GET.get("q", "").strip(),
                "selected_doctor": self.request.GET.get("doctor", "").strip(),
                "selected_shift": self.request.GET.get("shift", "").strip(),
                "selected_status": self.request.GET.get("status", "").strip(),
                "selected_visit_type": self.request.GET.get("visit_type", "").strip(),
                "selected_priority_level": self.request.GET.get("priority_level", "").strip(),
                "waiting_groups": self._build_waiting_groups(waiting_appointments),
                "walk_in_form": kwargs.get("walk_in_form") or ReceptionWalkInForm(),
            }
        )
        return context

    def _get_today_queryset(self):
        return doctor_scoped_appointments(
            Appointment.objects.select_related(
                "patient",
                "doctor_schedule__doctor",
                "doctor_schedule__shift",
                "service",
                "checked_in_by",
            )
            .prefetch_related("patient__invoices")
            .filter(doctor_schedule__work_date=timezone.localdate())
            .order_by("doctor_schedule__shift__start_time", "start_time", "patient__full_name"),
            self.request.user,
        )

    def _get_filtered_queryset(self):
        queryset = self._get_today_queryset()
        keyword = self.request.GET.get("q", "").strip()
        doctor_id = self.request.GET.get("doctor", "").strip()
        shift_id = self.request.GET.get("shift", "").strip()
        status = self.request.GET.get("status", "").strip()
        visit_type = self.request.GET.get("visit_type", "").strip()
        priority_level = self.request.GET.get("priority_level", "").strip()

        if keyword:
            queryset = queryset.filter(
                Q(appointment_code__icontains=keyword)
                | Q(patient__patient_code__icontains=keyword)
                | Q(patient__full_name__icontains=keyword)
                | Q(patient__phone__icontains=keyword)
                | Q(chief_complaint__icontains=keyword)
            )
        if doctor_id:
            queryset = queryset.filter(doctor_schedule__doctor_id=doctor_id)
        if shift_id:
            queryset = queryset.filter(doctor_schedule__shift_id=shift_id)
        if status:
            queryset = queryset.filter(status=status)
        if visit_type:
            queryset = queryset.filter(visit_type=visit_type)
        if priority_level:
            queryset = queryset.filter(priority_level=priority_level)
        return queryset

    def _get_today_shifts(self):
        schedules = DoctorSchedule.objects.filter(
                work_date=timezone.localdate(),
                status=DoctorSchedule.Status.REGISTERED,
                shift__is_active=True,
            )
        doctor = get_doctor_profile(self.request.user)
        if doctor:
            schedules = schedules.filter(doctor=doctor)
        shift_ids = (
            schedules
            .values_list("shift_id", flat=True)
            .distinct()
        )
        return WorkShift.objects.filter(pk__in=shift_ids).order_by("start_time", "name")

    def _attach_reception_alerts(self, appointments):
        for appointment in appointments:
            appointment.medical_alerts = get_medical_alerts_for_patient(appointment.patient)
            appointment.admin_alerts = get_admin_alerts_for_patient(appointment.patient)
            appointment.can_check_in = appointment.status in {Appointment.Status.SCHEDULED, Appointment.Status.CONFIRMED}

    def _build_waiting_groups(self, appointments):
        groups = {}
        for appointment in sorted(
            appointments,
            key=lambda item: (
                item.doctor_schedule.doctor.full_name,
                get_priority_rank(item.priority_level),
                item.queue_number or 999999,
                item.checked_in_at or item.created_at,
                item.start_time,
            ),
        ):
            doctor = appointment.doctor_schedule.doctor
            doctor_group = groups.setdefault(
                doctor.pk,
                {
                    "doctor": doctor,
                    "appointments": [],
                },
            )
            doctor_group["appointments"].append(appointment)
        return list(groups.values())


class AppointmentCheckInView(StaffRequiredMixin, View):
    permission_required = "clinic.change_appointment"

    def post(self, request, pk):
        appointment = get_object_or_404(
            doctor_scoped_appointments(
                Appointment.objects.select_related("doctor_schedule__doctor", "patient"),
                request.user,
            ),
            pk=pk,
        )
        redirect_url = self._get_redirect_url(request)

        if appointment.appointment_date != timezone.localdate():
            messages.error(request, "Chỉ có thể tiếp đón lịch hẹn trong ngày hôm nay.")
            return redirect(redirect_url)

        if appointment.status not in {Appointment.Status.SCHEDULED, Appointment.Status.CONFIRMED}:
            messages.warning(request, "Lịch hẹn này không còn ở trạng thái sẵn sàng để tiếp đón.")
            return redirect(redirect_url)

        before = self.serialize_model(appointment)
        appointment.status = Appointment.Status.CHECKED_IN
        appointment.checked_in_at = timezone.now()
        appointment.checked_in_by = request.user
        if not appointment.queue_number:
            appointment.queue_number = get_next_queue_number(appointment.doctor_schedule)
        appointment.save(update_fields=["status", "checked_in_at", "checked_in_by", "queue_number", "updated_at"])

        after = self.serialize_model(appointment)
        self.log_audit_event(
            "update",
            target=appointment,
            metadata={
                "before": before,
                "after": after,
                "changes": self.diff_snapshots(before, after),
            },
        )
        messages.success(
            request,
            f"Đã tiếp đón bệnh nhân {appointment.patient.full_name} vào hàng chờ của bác sĩ {appointment.doctor.full_name}.",
        )
        return redirect(redirect_url)

    def _get_redirect_url(self, request):
        next_url = request.POST.get("next", "").strip()
        if next_url.startswith("/"):
            return next_url
        return reverse("clinic:reception-today")


class ReceptionWalkInCreateView(StaffRequiredMixin, FormView):
    form_class = ReceptionWalkInForm
    permission_required = "clinic.add_appointment"

    def form_valid(self, form):
        doctor_schedule = form.cleaned_data["doctor_schedule"]
        doctor = get_doctor_profile(self.request.user)
        if doctor and doctor_schedule.doctor_id != doctor.pk:
            messages.error(self.request, "Bạn chỉ có thể tiếp nhận bệnh nhân vào lịch trực của mình.")
            return redirect(reverse("clinic:reception-today"))
        service = form.cleaned_data.get("service")
        start_time, end_time = find_next_walk_in_slot(
            doctor_schedule,
            getattr(service, "duration_minutes", None) or 30,
        )

        if not start_time or not end_time:
            messages.error(
                self.request,
                "Ca trực đã kín hoặc đã kết thúc. Hãy chọn lịch trực khác để tiếp nhận bệnh nhân không hẹn trước.",
            )
            return redirect(reverse("clinic:reception-today"))

        with transaction.atomic():
            try:
                patient = form.save_patient()
                appointment = Appointment(
                    patient=patient,
                    doctor_schedule=doctor_schedule,
                    service=service,
                    start_time=start_time,
                    end_time=end_time,
                    arrival_type=Appointment.ArrivalType.WALK_IN,
                    visit_type=form.cleaned_data["visit_type"],
                    priority_level=form.cleaned_data["priority_level"],
                    status=Appointment.Status.CHECKED_IN,
                    queue_number=get_next_queue_number(doctor_schedule),
                    checked_in_at=timezone.now(),
                    checked_in_by=self.request.user,
                    chief_complaint=form.cleaned_data["chief_complaint"],
                    note=form.cleaned_data.get("note", ""),
                )
                appointment.full_clean()
                appointment.save()
            except ValidationError as exc:
                transaction.set_rollback(True)
                messages.error(
                    self.request,
                    "; ".join(
                        error
                        for errors in exc.message_dict.values()
                        for error in errors
                    ) if hasattr(exc, "message_dict") else "; ".join(exc.messages),
                )
                return redirect(reverse("clinic:reception-today"))

        self.log_audit_event(
            "create",
            target=appointment,
            metadata={"after": self.serialize_model(appointment)},
        )
        messages.success(
            self.request,
            f"Đã tiếp nhận bệnh nhân {patient.full_name} vào hàng chờ của bác sĩ {doctor_schedule.doctor.full_name}.",
        )
        return redirect(reverse("clinic:reception-today"))

    def form_invalid(self, form):
        error_message = "; ".join(
            error
            for field_errors in form.errors.values()
            for error in field_errors
        )
        messages.error(self.request, error_message or "Không thể tiếp nhận bệnh nhân không hẹn trước.")
        return redirect(reverse("clinic:reception-today"))


class AppointmentCalendarView(StaffRequiredMixin, TemplateView):
    template_name = "clinic/appointment_calendar.html"
    permission_required = "clinic.view_appointment"
    slot_interval = 30

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        selected_date = parse_date(self.request.GET.get("date", "")) or timezone.localdate()
        week_start = selected_date - timedelta(days=selected_date.weekday())
        week_end = week_start + timedelta(days=6)
        selected_doctor = self.request.GET.get("doctor", "").strip()
        if selected_doctor and not selected_doctor.isdigit():
            selected_doctor = ""
        selected_status = self.request.GET.get("status", "").strip()

        appointments = list(
            self._get_appointment_queryset(week_start, week_end, selected_doctor, selected_status)
        )
        schedules = list(self._get_schedule_queryset(week_start, week_end, selected_doctor))
        calendar_days = self._build_calendar_days(week_start, schedules)
        slot_minutes = self._build_slot_minutes(appointments, schedules)
        rows = self._build_calendar_rows(calendar_days, slot_minutes, appointments, selected_doctor)

        context.update(
            {
                "calendar_days": calendar_days,
                "calendar_rows": rows,
                "doctors": doctor_choices_for_user(self.request.user),
                "selected_date": selected_date,
                "selected_doctor": selected_doctor,
                "selected_status": selected_status,
                "status_choices": Appointment.Status.choices,
                "week_start": week_start,
                "week_end": week_end,
                "previous_week_url": self._build_calendar_url(week_start - timedelta(days=7), selected_doctor, selected_status),
                "next_week_url": self._build_calendar_url(week_start + timedelta(days=7), selected_doctor, selected_status),
                "today_url": self._build_calendar_url(timezone.localdate(), selected_doctor, selected_status),
                "appointment_count": len(appointments),
                "status_summary": self._build_status_summary(appointments),
            }
        )
        return context

    def _get_appointment_queryset(self, week_start, week_end, selected_doctor, selected_status):
        queryset = doctor_scoped_appointments(Appointment.objects.select_related(
            "patient",
            "doctor_schedule__doctor",
            "doctor_schedule__shift",
            "service",
        ).filter(doctor_schedule__work_date__range=(week_start, week_end)), self.request.user)
        if selected_doctor:
            queryset = queryset.filter(doctor_schedule__doctor_id=selected_doctor)
        if selected_status:
            queryset = queryset.filter(status=selected_status)
        return queryset.order_by("doctor_schedule__work_date", "start_time", "doctor_schedule__doctor__full_name")

    def _get_schedule_queryset(self, week_start, week_end, selected_doctor):
        queryset = DoctorSchedule.objects.select_related("doctor", "shift").filter(
            work_date__range=(week_start, week_end),
            status=DoctorSchedule.Status.REGISTERED,
        )
        doctor = get_doctor_profile(self.request.user)
        if doctor:
            queryset = queryset.filter(doctor=doctor)
        if selected_doctor:
            queryset = queryset.filter(doctor_id=selected_doctor)
        return queryset.order_by("work_date", "shift__start_time", "doctor__full_name")

    def _build_calendar_days(self, week_start, schedules):
        today = timezone.localdate()
        schedule_counts = {}
        for schedule in schedules:
            schedule_counts[schedule.work_date] = schedule_counts.get(schedule.work_date, 0) + 1

        weekday_labels = ["Thứ hai", "Thứ ba", "Thứ tư", "Thứ năm", "Thứ sáu", "Thứ bảy", "Chủ nhật"]
        days = []
        for offset, weekday_label in enumerate(weekday_labels):
            current_date = week_start + timedelta(days=offset)
            days.append(
                {
                    "date": current_date,
                    "weekday_label": weekday_label,
                    "is_today": current_date == today,
                    "schedule_count": schedule_counts.get(current_date, 0),
                }
            )
        return days

    def _build_slot_minutes(self, appointments, schedules):
        start_candidates = [minutes_from_time(schedule.shift.start_time) for schedule in schedules]
        start_candidates.extend(minutes_from_time(appointment.start_time) for appointment in appointments)
        end_candidates = [minutes_from_time(schedule.shift.end_time) for schedule in schedules]
        end_candidates.extend(minutes_from_time(appointment.end_time) for appointment in appointments)

        if start_candidates and end_candidates:
            start_minutes = min(8 * 60, floor_to_slot(min(start_candidates), self.slot_interval))
            end_minutes = max(18 * 60, ceil_to_slot(max(end_candidates), self.slot_interval))
        else:
            start_minutes = 8 * 60
            end_minutes = 18 * 60

        end_minutes = min(end_minutes, 24 * 60)
        return list(range(start_minutes, end_minutes, self.slot_interval))

    def _build_calendar_rows(self, calendar_days, slot_minutes, appointments, selected_doctor):
        event_map = {}
        for appointment in appointments:
            appointment_date = appointment.appointment_date
            slot = floor_to_slot(minutes_from_time(appointment.start_time), self.slot_interval)
            duration = minutes_from_time(appointment.end_time) - minutes_from_time(appointment.start_time)
            event_map.setdefault((appointment_date, slot), []).append(
                {
                    "appointment": appointment,
                    "status_class": f"status-{appointment.status}",
                    "duration_label": f"{duration} phút" if duration > 0 else "",
                }
            )

        rows = []
        create_base_url = reverse("clinic:appointment-create")
        for slot in slot_minutes:
            slot_time = time_from_minutes(slot)
            slot_label = slot_time.strftime("%H:%M")
            cells = []
            for day in calendar_days:
                create_params = {"date": day["date"].isoformat(), "start_time": slot_label}
                if selected_doctor:
                    create_params["doctor"] = selected_doctor
                cells.append(
                    {
                        "date": day["date"],
                        "slot_label": slot_label,
                        "appointments": event_map.get((day["date"], slot), []),
                        "create_url": f"{create_base_url}?{urlencode(create_params)}",
                    }
                )
            rows.append({"slot_label": slot_label, "cells": cells})
        return rows

    def _build_calendar_url(self, date_value, selected_doctor, selected_status):
        params = {"date": date_value.isoformat()}
        if selected_doctor:
            params["doctor"] = selected_doctor
        if selected_status:
            params["status"] = selected_status
        return f"{reverse('clinic:appointment-calendar')}?{urlencode(params)}"

    def _build_status_summary(self, appointments):
        counts = {}
        for appointment in appointments:
            counts[appointment.status] = counts.get(appointment.status, 0) + 1
        return [
            {"value": value, "label": label, "count": counts.get(value, 0)}
            for value, label in Appointment.Status.choices
        ]


class AppointmentDetailView(StaffRequiredMixin, DetailView):
    model = Appointment
    template_name = "clinic/appointment_detail.html"
    context_object_name = "appointment"

    def get_queryset(self):
        queryset = Appointment.objects.select_related(
            "patient",
            "doctor_schedule__doctor",
            "doctor_schedule__shift",
            "service",
            "checked_in_by",
        ).prefetch_related("patient__invoices")
        return doctor_scoped_appointments(queryset, self.request.user)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if self.request.user.has_perm("clinic.view_invoice"):
            context["invoices"] = self.object.invoices.order_by("-issue_date", "-id")
        context["prescriptions"] = doctor_scoped_prescriptions(
            self.object.prescriptions.select_related("doctor"),
            self.request.user,
        ).order_by(
            "-prescribed_at",
            "-id",
        )
        context["medical_alerts"] = get_medical_alerts_for_patient(self.object.patient)
        context["admin_alerts"] = get_admin_alerts_for_patient(self.object.patient)
        return context


class AppointmentCreateView(StaffRequiredMixin, CreateView):
    model = Appointment
    form_class = AppointmentForm
    template_name = "clinic/appointment_form.html"

    def get_initial(self):
        initial = super().get_initial()
        work_date = parse_date(self.request.GET.get("date", ""))
        start_time = parse_time(self.request.GET.get("start_time", ""))
        selected_doctor = self.request.GET.get("doctor", "").strip()

        if start_time:
            initial["start_time"] = start_time
            end_minutes = minutes_from_time(start_time) + 30
            if end_minutes < 24 * 60:
                initial["end_time"] = time_from_minutes(end_minutes)

        if work_date and start_time:
            schedule_queryset = DoctorSchedule.objects.filter(
                work_date=work_date,
                status=DoctorSchedule.Status.REGISTERED,
                shift__start_time__lte=start_time,
                shift__end_time__gt=start_time,
            )
            if selected_doctor.isdigit():
                schedule_queryset = schedule_queryset.filter(doctor_id=selected_doctor)
            schedule = schedule_queryset.order_by("shift__start_time", "doctor__full_name").first()
            if schedule:
                initial["doctor_schedule"] = schedule
        return initial

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["staff_user"] = self.request.user
        return kwargs

    def get_success_url(self):
        return reverse("clinic:appointment-detail", kwargs={"pk": self.object.pk})

    def form_valid(self, form):
        messages.success(self.request, "Đã đăng ký lịch khám.")
        return super().form_valid(form)


class AppointmentUpdateView(StaffRequiredMixin, UpdateView):
    model = Appointment
    form_class = AppointmentForm
    template_name = "clinic/appointment_form.html"

    def get_form_class(self):
        if is_doctor_user(self.request.user):
            return DoctorAppointmentForm
        return super().get_form_class()

    def get_queryset(self):
        return doctor_scoped_appointments(super().get_queryset(), self.request.user)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["staff_user"] = self.request.user
        return kwargs

    def get_success_url(self):
        return reverse("clinic:appointment-detail", kwargs={"pk": self.object.pk})

    def form_valid(self, form):
        messages.success(self.request, "Đã cập nhật lịch khám.")
        return super().form_valid(form)


class AppointmentDeleteView(StaffRequiredMixin, DeleteView):
    model = Appointment
    template_name = "clinic/appointment_confirm_delete.html"
    success_url = reverse_lazy("clinic:appointment-list")

    def get_queryset(self):
        return doctor_scoped_appointments(super().get_queryset(), self.request.user)

    def form_valid(self, form):
        messages.success(self.request, "Đã xóa lịch khám.")
        return super().form_valid(form)


# ═══════════════════════════════════════════════════════════════════
# Messaging Views (Staff / System Dashboard)
# ═══════════════════════════════════════════════════════════════════


class StaffConversationListView(StaffRequiredMixin, ListView):
    """Danh sách tất cả cuộc hội thoại hỗ trợ."""
    model = Conversation
    template_name = "clinic/conversation_list.html"
    context_object_name = "conversations"
    paginate_by = LIST_PAGE_SIZE
    permission_required = "users.view_support_conversation"

    def get_queryset(self):
        queryset = Conversation.objects.select_related(
            "patient", "assigned_staff"
        ).order_by("-updated_at")

        status = self.request.GET.get("status", "").strip()
        keyword = self.request.GET.get("q", "").strip()

        if status == "open":
            queryset = queryset.filter(is_closed=False)
        elif status == "closed":
            queryset = queryset.filter(is_closed=True)
        elif status == "unassigned":
            queryset = queryset.filter(is_closed=False, assigned_staff__isnull=True)

        if keyword:
            queryset = queryset.filter(
                Q(subject__icontains=keyword)
                | Q(patient__full_name__icontains=keyword)
                | Q(patient__patient_code__icontains=keyword)
            )

        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["selected_status"] = self.request.GET.get("status", "").strip()
        context["keyword"] = self.request.GET.get("q", "").strip()
        context["pagination_query"] = get_pagination_query(self.request)
        # Đếm thống kê
        context["total_open"] = Conversation.objects.filter(is_closed=False).count()
        context["total_unassigned"] = Conversation.objects.filter(
            is_closed=False, assigned_staff__isnull=True
        ).count()
        return context


class StaffConversationDetailView(StaffRequiredMixin, TemplateView):
    """Xem chi tiết cuộc hội thoại và trả lời."""
    template_name = "clinic/conversation_detail.html"
    permission_required = "users.view_support_conversation"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        conversation = get_object_or_404(
            Conversation.objects.select_related("patient", "assigned_staff"),
            pk=self.kwargs["pk"],
        )
        messages_qs = conversation.messages.select_related("sender").order_by("created_at")

        # Đánh dấu đã đọc các tin nhắn mà bệnh nhân gửi
        if conversation.patient.user_id:
            messages_qs.filter(
                is_read=False, sender=conversation.patient.user
            ).update(is_read=True)

        context["conversation"] = conversation
        context["chat_messages"] = messages_qs
        return context


class StaffMessageSendView(StaffRequiredMixin, View):
    """AJAX endpoint — Nhân viên gửi tin nhắn."""
    permission_required = "users.manage_support_conversation"

    def post(self, request, pk):
        conversation = get_object_or_404(Conversation, pk=pk)

        if conversation.is_closed:
            return JsonResponse({"error": "Cuộc hội thoại đã đóng."}, status=400)

        content = request.POST.get("content", "").strip()
        if not content:
            return JsonResponse({"error": "Nội dung không được để trống."}, status=400)
        if len(content) > 2000:
            return JsonResponse({"error": "Nội dung không được vượt quá 2000 ký tự."}, status=400)

        # Tự động assign nếu chưa có
        if not conversation.assigned_staff_id:
            if hasattr(request.user, "staff_profile"):
                conversation.assigned_staff = request.user.staff_profile

        msg = Message.objects.create(
            conversation=conversation,
            sender=request.user,
            content=content,
        )
        conversation.save(update_fields=["assigned_staff_id", "updated_at"])

        return JsonResponse({
            "id": msg.pk,
            "content": msg.content,
            "sender": request.user.get_full_name() or request.user.username,
            "is_mine": True,
            "created_at": msg.created_at.strftime("%H:%M %d/%m/%Y"),
        })


class StaffMessagePollView(StaffRequiredMixin, View):
    """AJAX endpoint — Lấy tin nhắn mới cho nhân viên."""
    permission_required = "users.view_support_conversation"

    def get(self, request, pk):
        conversation = get_object_or_404(Conversation, pk=pk)
        after_id = int(request.GET.get("after_id", 0))

        new_messages = (
            conversation.messages
            .filter(pk__gt=after_id)
            .select_related("sender")
            .order_by("created_at")
        )

        # Đánh dấu đã đọc tin nhắn từ bệnh nhân
        if conversation.patient.user_id:
            new_messages.filter(
                is_read=False, sender=conversation.patient.user
            ).update(is_read=True)

        data = []
        for msg in new_messages:
            data.append({
                "id": msg.pk,
                "content": msg.content,
                "sender": msg.sender.get_full_name() or msg.sender.username,
                "is_mine": msg.sender == request.user,
                "created_at": msg.created_at.strftime("%H:%M %d/%m/%Y"),
            })

        return JsonResponse({"messages": data, "is_closed": conversation.is_closed})


class StaffConversationAssignView(StaffRequiredMixin, View):
    """Nhân viên tự assign mình vào cuộc hội thoại."""
    permission_required = "users.manage_support_conversation"

    def post(self, request, pk):
        conversation = get_object_or_404(Conversation, pk=pk)
        if hasattr(request.user, "staff_profile"):
            conversation.assigned_staff = request.user.staff_profile
            conversation.save(update_fields=["assigned_staff_id", "updated_at"])
            messages.success(request, "Bạn đã nhận hỗ trợ cuộc hội thoại này.")
        return redirect("clinic:conversation-detail", pk=conversation.pk)


class StaffConversationCloseView(StaffRequiredMixin, View):
    """Nhân viên đóng cuộc hội thoại."""
    permission_required = "users.manage_support_conversation"

    def post(self, request, pk):
        conversation = get_object_or_404(Conversation, pk=pk)
        conversation.is_closed = True
        conversation.save(update_fields=["is_closed", "updated_at"])
        messages.success(request, "Đã đóng cuộc hội thoại.")
        return redirect("clinic:conversation-detail", pk=conversation.pk)
