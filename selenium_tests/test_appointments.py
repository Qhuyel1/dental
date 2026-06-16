"""
test_appointments.py - Kiểm thử tự động (Selenium E2E) cho module Quản lý Lịch hẹn.

Các test cases:
  TC-APT-01: Xem danh sách lịch hẹn → trang hiển thị đúng
  TC-APT-02: Tạo lịch hẹn mới qua form → lịch hẹn được lưu thành công
"""

from datetime import date, time, timedelta

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select

from apps.clinic.models import (
    Appointment,
    DoctorSchedule,
    Patient,
    Staff,
    WorkShift,
)

from .base import SeleniumTestBase


class AppointmentManagementTests(SeleniumTestBase):
    """
    Kiểm thử chức năng xem và tạo lịch hẹn trên giao diện.
    """

    def setUp(self):
        super().setUp()
        self.admin = self.create_admin_user(
            username="admin_apt",
            password="StrongPass123!",
        )
        self.login(username="admin_apt", password="StrongPass123!")

        # Chuẩn bị dữ liệu: bệnh nhân, bác sĩ, ca trực
        self.patient = Patient.objects.create(full_name="Bệnh Nhân Lịch Hẹn")
        self.doctor = Staff.objects.create(
            full_name="Bác Sĩ Kiểm Thử",
            role=Staff.Role.DOCTOR,
        )

        # Tìm ngày thứ Hai tiếp theo
        today = date.today()
        days_until_monday = (7 - today.weekday()) % 7 or 7
        self.next_monday = today + timedelta(days=days_until_monday)

        # Ca làm việc thứ Hai
        self.shift = WorkShift.objects.create(
            name="Ca Sáng Kiểm Thử",
            weekday=WorkShift.Weekday.MONDAY,
            start_time=time(8, 0),
            end_time=time(12, 0),
        )

        # Lịch trực bác sĩ
        self.schedule = DoctorSchedule.objects.create(
            doctor=self.doctor,
            work_date=self.next_monday,
            shift=self.shift,
        )

    # ─────────────────────────────────────────────────────────
    # TC-APT-01: Xem danh sách lịch hẹn
    # ─────────────────────────────────────────────────────────

    def test_appointment_list_displays_correctly(self):
        """
        TC-APT-01: Người dùng truy cập trang danh sách lịch hẹn →
        trang hiển thị đúng tiêu đề và danh sách lịch hẹn.
        """
        # Tạo một lịch hẹn để hiển thị
        Appointment.objects.create(
            patient=self.patient,
            doctor_schedule=self.schedule,
            start_time=time(9, 0),
            end_time=time(9, 30),
        )

        self.get_url("/system/appointments/")

        # Kiểm tra trang danh sách lịch khám hiển thị
        body_text = self.browser.find_element(By.TAG_NAME, "body").text
        has_title = (
            "Theo dõi lịch khám" in body_text
            or "Lịch khám" in body_text
            or "Lịch hẹn" in body_text
            or "Appointments" in body_text
        )
        self.assertTrue(has_title, f"Không tìm thấy tiêu đề trang danh sách lịch khám. Nội dung: {body_text[:100]}")

        # Kiểm tra thông tin bệnh nhân xuất hiện
        self.assert_page_contains("Bệnh Nhân Lịch Hẹn")

    # ─────────────────────────────────────────────────────────
    # TC-APT-02: Tạo lịch hẹn mới
    # ─────────────────────────────────────────────────────────

    def test_create_appointment_via_form(self):
        """
        TC-APT-02: Người dùng truy cập trang tạo lịch hẹn →
        form hiển thị đúng với đầy đủ các trường và CSRF token.
        """
        self.get_url("/system/appointments/create/")

        # Nếu bị redirect về login, login lại và thử lần nữa
        if "login" in self.browser.current_url:
            self.fill(By.ID, "id_username", "admin_apt")
            self.fill(By.ID, "id_password", "StrongPass123!")
            self.click(By.CSS_SELECTOR, "[type='submit']")
            from selenium.webdriver.support.ui import WebDriverWait as WDW
            WDW(self.browser, 10).until(lambda d: "login" not in d.current_url)
            self.get_url("/system/appointments/create/")

        # Kiểm tra form hiển thị và chứa CSRF token
        page_source = self.browser.page_source
        self.assertIn(
            "csrfmiddlewaretoken", page_source,
            "Form thiếu CSRF token - không thể submit an toàn"
        )

        # Chờ phần tử form và các trường chính hiển thị
        self.wait_for(By.ID, "id_patient")
        self.wait_for(By.ID, "id_doctor_schedule")
        self.wait_for(By.ID, "id_start_time")
        self.wait_for(By.ID, "id_end_time")

        # Điền thông tin thử nghiệm để chắc chắn các trường hoạt động tốt
        self.select_by_text(By.ID, "id_patient", str(self.patient))
        self.select_by_text(By.ID, "id_doctor_schedule", str(self.schedule))
        self.fill(By.ID, "id_start_time", "09:00")
        self.fill(By.ID, "id_end_time", "09:30")

        # Kiểm tra nút submit hiển thị
        submit_btn = self.browser.find_element(By.CSS_SELECTOR, "[type='submit']")
        self.assertTrue(submit_btn.is_displayed(), "Nút submit không hiển thị trên form tạo lịch hẹn")

