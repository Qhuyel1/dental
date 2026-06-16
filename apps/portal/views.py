from django.contrib.auth import views as auth_views
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import JsonResponse
from django.shortcuts import redirect, get_object_or_404
from django.urls import reverse_lazy, reverse
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views import View
from django.views.generic import TemplateView, ListView, CreateView

from apps.clinic.models import Appointment, Invoice, Prescription
from apps.users.forms import LoginForm

from .models import Conversation, Message


class PortalLoginView(auth_views.LoginView):
    template_name = "portal/login.html"
    authentication_form = LoginForm
    redirect_authenticated_user = True

    def get(self, request, *args, **kwargs):
        if self.redirect_authenticated_user and self.request.user.is_authenticated:
            if hasattr(self.request.user, "patient_profile"):
                return redirect(self.get_success_url())
        return super().get(request, *args, **kwargs)

    def form_valid(self, form):
        user = form.get_user()
        if not hasattr(user, "patient_profile"):
            form.add_error(None, _("Tài khoản này không phải là tài khoản bệnh nhân."))
            return self.form_invalid(form)
        return super().form_valid(form)

    def get_success_url(self):
        return reverse_lazy("portal:home")


class PortalLogoutView(auth_views.LogoutView):
    next_page = reverse_lazy("portal:login")


class PatientPortalMixin(LoginRequiredMixin):
    """
    Mixin dùng chung cho tất cả view trong Patient Portal.
    - Yêu cầu đăng nhập.
    - Yêu cầu tài khoản phải liên kết với một hồ sơ Patient.
    - Cung cấp self.patient để các view con dùng trực tiếp.
    """
    login_url = "portal:login"

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if not hasattr(request.user, "patient_profile"):
            # Tài khoản không phải bệnh nhân → chuyển về trang quản trị
            return redirect("clinic:dashboard")
        self.patient = request.user.patient_profile
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["patient"] = self.patient
        # Đếm tổng tin nhắn chưa đọc cho sidebar badge
        unread_total = 0
        for conv in Conversation.objects.filter(patient=self.patient, is_closed=False):
            unread_total += conv.messages.filter(is_read=False).exclude(
                sender=self.request.user
            ).count()
        context["unread_message_count"] = unread_total
        return context


class PortalHomeView(PatientPortalMixin, TemplateView):
    template_name = "portal/home.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        patient = self.patient
        context["upcoming_appointments"] = (
            Appointment.objects.filter(patient=patient)
            .exclude(status__in=["cancelled", "completed"])
            .select_related("doctor_schedule__doctor", "doctor_schedule__shift")
            .order_by("doctor_schedule__work_date")[:5]
        )
        context["unpaid_invoices"] = (
            Invoice.objects.filter(patient=patient, status="unpaid")
            .order_by("-created_at")[:5]
        )
        return context


class PortalProfileView(PatientPortalMixin, TemplateView):
    template_name = "portal/profile.html"


class PortalAppointmentListView(PatientPortalMixin, ListView):
    template_name = "portal/appointments.html"
    context_object_name = "appointments"
    paginate_by = 10

    def get_queryset(self):
        return (
            Appointment.objects.filter(patient=self.patient)
            .select_related("doctor_schedule__doctor", "doctor_schedule__shift", "service")
            .order_by("-doctor_schedule__work_date")
        )


class PortalInvoiceListView(PatientPortalMixin, ListView):
    template_name = "portal/invoices.html"
    context_object_name = "invoices"
    paginate_by = 10

    def get_queryset(self):
        return (
            Invoice.objects.filter(patient=self.patient)
            .prefetch_related("items__service")
            .order_by("-created_at")
        )


class PortalPrescriptionListView(PatientPortalMixin, ListView):
    template_name = "portal/prescriptions.html"
    context_object_name = "prescriptions"
    paginate_by = 10

    def get_queryset(self):
        return (
            Prescription.objects.filter(patient=self.patient)
            .select_related("doctor")
            .prefetch_related("items__medicine")
            .order_by("-created_at")
        )


# ═══════════════════════════════════════════════════════════════════
# Messaging Views (Patient Portal)
# ═══════════════════════════════════════════════════════════════════


class PortalConversationListView(PatientPortalMixin, ListView):
    """Danh sách cuộc hội thoại của bệnh nhân."""
    template_name = "portal/messages_list.html"
    context_object_name = "conversations"
    paginate_by = 10

    def get_queryset(self):
        return (
            Conversation.objects.filter(patient=self.patient)
            .select_related("assigned_staff")
            .order_by("-updated_at")
        )


class PortalConversationCreateView(PatientPortalMixin, TemplateView):
    """Tạo cuộc hội thoại mới."""
    template_name = "portal/messages_create.html"

    def post(self, request, *args, **kwargs):
        subject = request.POST.get("subject", "").strip()
        content = request.POST.get("content", "").strip()

        if not subject or not content:
            context = self.get_context_data()
            context["error"] = _("Vui lòng nhập đầy đủ tiêu đề và nội dung.")
            context["form_subject"] = subject
            context["form_content"] = content
            return self.render_to_response(context)

        if len(subject) > 200:
            context = self.get_context_data()
            context["error"] = _("Tiêu đề không được vượt quá 200 ký tự.")
            context["form_subject"] = subject
            context["form_content"] = content
            return self.render_to_response(context)

        if len(content) > 2000:
            context = self.get_context_data()
            context["error"] = _("Nội dung tin nhắn không được vượt quá 2000 ký tự.")
            context["form_subject"] = subject
            context["form_content"] = content
            return self.render_to_response(context)

        conversation = Conversation.objects.create(
            patient=self.patient,
            subject=subject,
        )
        Message.objects.create(
            conversation=conversation,
            sender=request.user,
            content=content,
        )
        return redirect("portal:messages-detail", pk=conversation.pk)


class PortalConversationDetailView(PatientPortalMixin, TemplateView):
    """Xem chi tiết cuộc hội thoại và gửi tin nhắn."""
    template_name = "portal/messages_detail.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        conversation = get_object_or_404(
            Conversation, pk=self.kwargs["pk"], patient=self.patient
        )
        messages_qs = conversation.messages.select_related("sender").order_by("created_at")

        # Đánh dấu đã đọc các tin nhắn mà nhân viên gửi
        messages_qs.filter(is_read=False).exclude(sender=self.request.user).update(is_read=True)

        context["conversation"] = conversation
        context["messages"] = messages_qs
        return context


class PortalMessageSendView(PatientPortalMixin, View):
    """AJAX endpoint — Bệnh nhân gửi tin nhắn."""

    def post(self, request, pk):
        conversation = get_object_or_404(
            Conversation, pk=pk, patient=self.patient
        )
        if conversation.is_closed:
            return JsonResponse({"error": _("Cuộc hội thoại đã đóng.")}, status=400)

        content = request.POST.get("content", "").strip()
        if not content:
            return JsonResponse({"error": _("Nội dung không được để trống.")}, status=400)
        if len(content) > 2000:
            return JsonResponse({"error": _("Nội dung không được vượt quá 2000 ký tự.")}, status=400)

        msg = Message.objects.create(
            conversation=conversation,
            sender=request.user,
            content=content,
        )
        # Cập nhật updated_at của conversation
        conversation.save(update_fields=["updated_at"])

        return JsonResponse({
            "id": msg.pk,
            "content": msg.content,
            "sender": request.user.get_full_name() or request.user.username,
            "is_mine": True,
            "created_at": msg.created_at.strftime("%H:%M %d/%m/%Y"),
        })


class PortalMessagePollView(PatientPortalMixin, View):
    """AJAX endpoint — Lấy tin nhắn mới cho bệnh nhân."""

    def get(self, request, pk):
        conversation = get_object_or_404(
            Conversation, pk=pk, patient=self.patient
        )
        after_id = int(request.GET.get("after_id", 0))

        new_messages = (
            conversation.messages
            .filter(pk__gt=after_id)
            .select_related("sender")
            .order_by("created_at")
        )

        # Đánh dấu đã đọc
        new_messages.filter(is_read=False).exclude(sender=request.user).update(is_read=True)

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


class PortalConversationCloseView(PatientPortalMixin, View):
    """Bệnh nhân đóng cuộc hội thoại."""

    def post(self, request, pk):
        conversation = get_object_or_404(
            Conversation, pk=pk, patient=self.patient
        )
        conversation.is_closed = True
        conversation.save(update_fields=["is_closed", "updated_at"])
        return redirect("portal:messages-detail", pk=conversation.pk)
