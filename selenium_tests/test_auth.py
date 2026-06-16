"""
test_auth.py - Kiểm thử tự động (Selenium E2E) cho module Xác thực (Authentication).

Các test cases:
  TC-AUTH-01: Đăng nhập thành công → chuyển hướng về Dashboard
  TC-AUTH-02: Đăng nhập sai mật khẩu → hiển thị thông báo lỗi
  TC-AUTH-03: Đăng xuất thành công → chuyển hướng về trang login
"""

from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from .base import SeleniumTestBase


class AuthenticationTests(SeleniumTestBase):
    """
    Kiểm thử chức năng đăng nhập / đăng xuất.

    Mỗi test tạo user trong database test riêng và kiểm tra
    hành vi thực tế trên giao diện trình duyệt.
    """

    def setUp(self):
        super().setUp()
        # Tạo user admin dùng chung cho các test auth
        self.admin = self.create_admin_user(
            username="admin_selenium",
            password="StrongPass123!",
        )

    # ─────────────────────────────────────────────────────────
    # TC-AUTH-01: Đăng nhập thành công
    # ─────────────────────────────────────────────────────────

    def test_login_success_redirects_to_dashboard(self):
        """
        TC-AUTH-01: Người dùng nhập đúng username và password →
        hệ thống chuyển hướng về trang Dashboard.
        """
        # Truy cập trang login
        self.get_url("/system/users/login/")

        # Kiểm tra form login hiển thị (trang dùng tiếng Anh: "Welcome back", "Log In")
        self.wait_for(By.ID, "id_username")
        body_text = self.browser.find_element(By.TAG_NAME, "body").text
        has_login_page = (
            "Welcome back" in body_text
            or "Log In" in body_text
            or "Đăng nhập" in body_text
            or "login" in self.browser.current_url.lower()
        )
        self.assertTrue(has_login_page, "Trang login không hiển thị đúng")

        # Điền thông tin đăng nhập
        self.fill(By.ID, "id_username", "admin_selenium")
        self.fill(By.ID, "id_password", "StrongPass123!")

        # Nhấn nút đăng nhập (Log In)
        self.click(By.CSS_SELECTOR, "[type='submit']")

        # Chờ chuyển hướng về dashboard (URL phải chứa /system/ và không phải login)
        WebDriverWait(self.browser, 10).until(
            lambda d: "/system/" in d.current_url and "login" not in d.current_url
        )

        # Kiểm tra đang ở trang dashboard
        self.assert_current_url_contains("/system/")

        # Kiểm tra nội dung dashboard: "Dashboard" hoặc "Quản lý hệ thống" hoặc username
        body_text = self.browser.find_element(By.TAG_NAME, "body").text
        has_dashboard = (
            "Dashboard" in body_text
            or "Quản lý hệ thống" in body_text
            or "admin_selenium" in body_text
        )
        self.assertTrue(has_dashboard, "Không hiển thị nội dung dashboard sau khi đăng nhập")

    # ─────────────────────────────────────────────────────────
    # TC-AUTH-02: Đăng nhập sai mật khẩu
    # ─────────────────────────────────────────────────────────

    def test_login_wrong_password_shows_error(self):
        """
        TC-AUTH-02: Người dùng nhập sai mật khẩu →
        hệ thống ở lại trang login và hiển thị thông báo lỗi.
        """
        self.get_url("/system/users/login/")

        # Nhập username đúng nhưng mật khẩu sai
        self.fill(By.ID, "id_username", "admin_selenium")
        self.fill(By.ID, "id_password", "SaiMatKhau123!")

        self.click(By.CSS_SELECTOR, "[type='submit']")

        # Chờ cho trang reload (username field xuất hiện lại)
        self.wait_for(By.ID, "id_username")
        import time as _time
        _time.sleep(1)  # chờ thêm để thông báo lỗi render

        # Vẫn ở trang login
        self.assertIn(
            "login",
            self.browser.current_url,
            "Đã bị chuyển hướng khỏi trang login dù mật khẩu sai",
        )

        # Kiểm tra có thông báo lỗi - dùng page_source để đảm bảo không bỏ sót
        page_source = self.browser.page_source
        has_error = any(phrase in page_source for phrase in [
            "correct username and password",  # Django default English
            "không đúng",
            "Vui lòng điền",                 # Django Vietnamese
            "chính xác",
            "incorrect",
            "Invalid",
            "invalid",
            "errorlist",                     # Django CSS class cho error
            "alert-danger",
            "error",
        ])
        self.assertTrue(has_error, f"Không thấy thông báo lỗi khi đăng nhập sai.")

    # ─────────────────────────────────────────────────────────
    # TC-AUTH-03: Đăng xuất thành công
    # ─────────────────────────────────────────────────────────

    def test_logout_redirects_to_login(self):
        """
        TC-AUTH-03: Sau khi đăng nhập, người dùng nhấn Đăng xuất →
        hệ thống chuyển hướng về trang login.
        """
        # Đăng nhập trước
        self.login(username="admin_selenium", password="StrongPass123!")

        # Xác nhận đang ở dashboard
        self.assert_current_url_contains("/system/")

        # Đăng xuất bằng cách click nút Đăng xuất trên giao diện
        self.logout()

        # Chờ chuyển hướng về trang login
        WebDriverWait(self.browser, 10).until(
            lambda d: "login" in d.current_url or d.current_url.endswith("/system/users/")
        )

        # Kiểm tra đã về trang login (form login xuất hiện lại)
        self.wait_for(By.ID, "id_username")

        # Kiểm tra trang login hiển thị
        body_text = self.browser.find_element(By.TAG_NAME, "body").text
        has_login_form = (
            "Welcome back" in body_text
            or "Log In" in body_text
            or "Đăng nhập" in body_text
        )
        self.assertTrue(has_login_form, "Không chuyển hướng về trang login sau khi đăng xuất")
