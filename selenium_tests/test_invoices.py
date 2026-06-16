"""
test_invoices.py - Kiểm thử tự động (Selenium E2E) cho module Quản lý Hóa đơn.

Các test cases:
  TC-INV-01: Xem danh sách hóa đơn → trang hiển thị đúng
  TC-INV-02: Xem chi tiết hóa đơn → thông tin hóa đơn hiển thị đầy đủ
"""

from datetime import date
from decimal import Decimal

from selenium.webdriver.common.by import By

from apps.clinic.models import Invoice, InvoiceItem, Patient, Service, ServiceCategory

from .base import SeleniumTestBase


class InvoiceManagementTests(SeleniumTestBase):
    """
    Kiểm thử chức năng xem danh sách và chi tiết hóa đơn.
    """

    def setUp(self):
        super().setUp()
        self.admin = self.create_admin_user(
            username="admin_inv",
            password="StrongPass123!",
        )
        self.login(username="admin_inv", password="StrongPass123!")

        # Chuẩn bị dữ liệu: bệnh nhân, dịch vụ, hóa đơn
        self.patient = Patient.objects.create(
            full_name="Bệnh Nhân Hóa Đơn",
            phone="0901111222",
        )
        self.category = ServiceCategory.objects.create(name="Nhổ Răng Kiểm Thử")
        self.service = Service.objects.create(
            category=self.category,
            name="Nhổ Răng Khôn",
        )
        self.invoice = Invoice.objects.create(
            patient=self.patient,
            issue_date=date.today(),
        )
        # Thêm dịch vụ vào hóa đơn
        InvoiceItem.objects.create(
            invoice=self.invoice,
            service=self.service,
            quantity=1,
            unit_price=Decimal("500000"),
        )
        self.invoice.refresh_from_db()

    # ─────────────────────────────────────────────────────────
    # TC-INV-01: Xem danh sách hóa đơn
    # ─────────────────────────────────────────────────────────

    def test_invoice_list_displays_correctly(self):
        """
        TC-INV-01: Người dùng truy cập trang danh sách hóa đơn →
        trang hiển thị đúng tiêu đề và danh sách hóa đơn.
        """
        self.get_url("/system/invoices/")

        # Kiểm tra tiêu đề trang (“Thanh toán và hóa đơn” hoặc “Hóa đơn”)
        body_text = self.browser.find_element(By.TAG_NAME, "body").text
        has_title = (
            "Hóa đơn" in body_text
            or "Thanh toán" in body_text
            or "Invoice" in body_text
        )
        self.assertTrue(has_title, f"Không tìm thấy tiêu đề trang danh sách hóa đơn. Nội dung: {body_text[:200]}")

        # Kiểm tra tên bệnh nhân xuất hiện trong danh sách
        self.assert_page_contains("Bệnh Nhân Hóa Đơn")

        # Kiểm tra mã hóa đơn xuất hiện (bắt đầu bằng HD-)
        self.assert_page_contains(self.invoice.invoice_code)

    # ─────────────────────────────────────────────────────────
    # TC-INV-02: Xem chi tiết hóa đơn
    # ─────────────────────────────────────────────────────────

    def test_invoice_detail_shows_correct_info(self):
        """
        TC-INV-02: Người dùng xem chi tiết hóa đơn →
        trang hiển thị đúng thông tin bệnh nhân, mã hóa đơn,
        dịch vụ và số tiền.
        """
        self.get_url(f"/system/invoices/{self.invoice.pk}/")

        # Kiểm tra mã hóa đơn
        self.assert_page_contains(self.invoice.invoice_code)

        # Kiểm tra tên bệnh nhân
        self.assert_page_contains("Bệnh Nhân Hóa Đơn")

        # Kiểm tra tên dịch vụ trong hóa đơn
        self.assert_page_contains("Nhổ Răng Khôn")

        # Kiểm tra số tiền hóa đơn (500,000 VND)
        body_text = self.browser.find_element(By.TAG_NAME, "body").text
        has_amount = "500" in body_text or "500.000" in body_text or "500,000" in body_text
        self.assertTrue(has_amount, "Số tiền hóa đơn không hiển thị đúng")

        # Kiểm tra trạng thái hóa đơn hiển thị
        has_status = (
            "Chưa thanh toán" in body_text
            or "Đã thanh toán" in body_text
            or "Còn nợ" in body_text
        )
        self.assertTrue(has_status, "Trạng thái hóa đơn không hiển thị")
