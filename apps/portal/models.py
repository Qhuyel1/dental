from django.conf import settings
from django.db import models

from apps.clinic.models import Patient, Staff


class Conversation(models.Model):
    """Cuộc hội thoại hỗ trợ giữa Bệnh nhân và Lễ tân/CSKH."""

    patient = models.ForeignKey(
        Patient,
        verbose_name="Bệnh nhân",
        on_delete=models.CASCADE,
        related_name="conversations",
    )
    assigned_staff = models.ForeignKey(
        Staff,
        verbose_name="Nhân viên hỗ trợ",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_conversations",
    )
    subject = models.CharField("Tiêu đề / lý do liên hệ", max_length=200)
    is_closed = models.BooleanField("Đã đóng", default=False)
    created_at = models.DateTimeField("Ngày tạo", auto_now_add=True)
    updated_at = models.DateTimeField("Cập nhật lần cuối", auto_now=True)

    class Meta:
        ordering = ["-updated_at"]
        verbose_name = "Cuộc hội thoại"
        verbose_name_plural = "Cuộc hội thoại"

    def __str__(self):
        return f"#{self.pk} - {self.subject} ({self.patient.full_name})"

    @property
    def last_message(self):
        return self.messages.order_by("-created_at").first()

    @property
    def unread_count_for_patient(self):
        """Số tin nhắn chưa đọc mà nhân viên gửi (bệnh nhân chưa đọc)."""
        return self.messages.filter(is_read=False).exclude(
            sender=self.patient.user
        ).count()

    @property
    def unread_count_for_staff(self):
        """Số tin nhắn chưa đọc mà bệnh nhân gửi (nhân viên chưa đọc)."""
        if not self.patient.user_id:
            return 0
        return self.messages.filter(
            is_read=False, sender=self.patient.user
        ).count()


class Message(models.Model):
    """Tin nhắn trong cuộc hội thoại."""

    conversation = models.ForeignKey(
        Conversation,
        verbose_name="Cuộc hội thoại",
        on_delete=models.CASCADE,
        related_name="messages",
    )
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="Người gửi",
        on_delete=models.CASCADE,
        related_name="sent_messages",
    )
    content = models.TextField("Nội dung", max_length=2000)
    is_read = models.BooleanField("Đã đọc", default=False)
    created_at = models.DateTimeField("Thời gian gửi", auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
        verbose_name = "Tin nhắn"
        verbose_name_plural = "Tin nhắn"

    def __str__(self):
        return f"Tin nhắn #{self.pk} - {self.sender}"
