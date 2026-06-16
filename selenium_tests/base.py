"""
base.py - Base class cho tất cả Selenium E2E tests trong dự án Dental Management.

Cung cấp:
  - SeleniumTestBase: kế thừa StaticLiveServerTestCase, khởi động Chrome headless
  - Helper methods: login(), logout(), wait_for(), click(), fill()
  - Tự động chụp screenshot khi test thất bại
"""

import os
import time
from datetime import date, timedelta
from pathlib import Path

from django.contrib.auth.models import User
from django.test import LiveServerTestCase

from selenium import webdriver
from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import Select, WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager

# Thư mục lưu screenshot khi test thất bại
SCREENSHOT_DIR = Path(__file__).resolve().parent / "screenshots"
SCREENSHOT_DIR.mkdir(exist_ok=True)

# Thời gian chờ tối đa (giây) cho các thao tác UI
DEFAULT_WAIT = 10


class SeleniumTestBase(LiveServerTestCase):
    """
    Base class cho tất cả Selenium tests.

    Mỗi test class kế thừa class này sẽ tự động:
    - Khởi động Chrome headless trước khi chạy test
    - Đóng browser sau khi test xong
    - Chụp screenshot vào selenium_tests/screenshots/ nếu test thất bại
    """

    @classmethod
    def setUpClass(cls):
        """Khởi tạo Chrome WebDriver (dùng chung cho cả test class)."""
        super().setUpClass()

        chrome_options = Options()
        # Chạy không hiển thị cửa sổ (Mặc định comment lại để anh/chị xem được trình duyệt tự chạy)
        # chrome_options.add_argument("--headless=new")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--window-size=1400,900")
        chrome_options.add_argument("--disable-gpu")
        # Bỏ log không cần thiết
        chrome_options.add_experimental_option("excludeSwitches", ["enable-logging"])

        # webdriver-manager tự tải đúng phiên bản ChromeDriver
        service = Service(ChromeDriverManager().install())
        cls.browser = webdriver.Chrome(service=service, options=chrome_options)
        cls.browser.implicitly_wait(5)

    @classmethod
    def tearDownClass(cls):
        """Đóng browser sau khi tất cả tests trong class kết thúc."""
        cls.browser.quit()
        super().tearDownClass()

    def setUp(self):
        """Reset trạng thái browser trước mỗi test."""
        self.browser.delete_all_cookies()

    def tearDown(self):
        """Chụp screenshot nếu test thất bại."""
        if self._outcome.errors:
            for method, error in self._outcome.errors:
                if error:
                    test_name = self._testMethodName
                    timestamp = time.strftime("%Y%m%d_%H%M%S")
                    filename = SCREENSHOT_DIR / f"FAIL_{test_name}_{timestamp}.png"
                    try:
                        self.browser.save_screenshot(str(filename))
                        print(f"\n📸 Screenshot lưu tại: {filename}")
                    except WebDriverException:
                        pass

    # ─────────────────────────────────────────
    # Helper: Điều hướng
    # ─────────────────────────────────────────

    def get_url(self, path: str):
        """Điều hướng đến URL tương đối (ví dụ: '/system/users/login/')."""
        self.browser.get(f"{self.live_server_url}{path}")

    # ─────────────────────────────────────────
    # Helper: Chờ đợi phần tử
    # ─────────────────────────────────────────

    def wait_for(self, by, value, timeout=DEFAULT_WAIT):
        """Chờ cho đến khi phần tử xuất hiện và có thể nhìn thấy."""
        return WebDriverWait(self.browser, timeout).until(
            EC.visibility_of_element_located((by, value))
        )

    def wait_for_clickable(self, by, value, timeout=DEFAULT_WAIT):
        """Chờ cho đến khi phần tử có thể click."""
        return WebDriverWait(self.browser, timeout).until(
            EC.element_to_be_clickable((by, value))
        )

    def wait_for_text(self, text: str, timeout=DEFAULT_WAIT):
        """Chờ cho đến khi text xuất hiện trên trang."""
        return WebDriverWait(self.browser, timeout).until(
            EC.text_to_be_present_in_element((By.TAG_NAME, "body"), text)
        )

    def wait_for_url_contains(self, partial_url: str, timeout=DEFAULT_WAIT):
        """Chờ cho đến khi URL hiện tại chứa chuỗi partial_url."""
        return WebDriverWait(self.browser, timeout).until(
            EC.url_contains(partial_url)
        )

    # ─────────────────────────────────────────
    # Helper: Tương tác form
    # ─────────────────────────────────────────

    def fill(self, by, value, text: str, clear_first=True):
        """Điền text vào input field."""
        element = self.wait_for(by, value)
        if clear_first:
            element.clear()
        element.send_keys(text)
        return element

    def click(self, by, value):
        """Click vào phần tử."""
        element = self.wait_for_clickable(by, value)
        element.click()
        return element

    def select_by_text(self, by, value, text: str):
        """Chọn option trong <select> theo visible text."""
        element = self.wait_for(by, value)
        Select(element).select_by_visible_text(text)

    def select_by_value(self, by, value, option_value: str):
        """Chọn option trong <select> theo value."""
        element = self.wait_for(by, value)
        Select(element).select_by_value(option_value)

    # ─────────────────────────────────────────
    # Helper: Xác thực (Auth)
    # ─────────────────────────────────────────

    def create_admin_user(self, username="admin_test", password="StrongPass123!"):
        """Tạo user admin trong database test."""
        return User.objects.create_user(
            username=username,
            password=password,
            is_staff=True,
            is_superuser=True,
        )

    def login(self, username="admin_test", password="StrongPass123!"):
        """Đăng nhập qua giao diện trình duyệt."""
        self.get_url("/system/users/login/")
        login_url = self.browser.current_url
        self.fill(By.ID, "id_username", username)
        self.fill(By.ID, "id_password", password)
        self.click(By.CSS_SELECTOR, "[type='submit']")
        # Chờ URL thay đổi khỏi trang login (tức là đã redirect)
        WebDriverWait(self.browser, DEFAULT_WAIT).until(
            lambda d: d.current_url != login_url
        )

    def logout(self):
        """Đăng xuất bằng cách click nút Đăng xuất trên giao diện.
        Django 4.1+ chỉ chấp nhận POST cho logout.
        """
        self.get_url("/system/")
        try:
            # Tìm và click nút Đăng xuất
            logout_btn = self.wait_for_clickable(
                By.XPATH,
                "//*[contains(text(), 'Đăng xuất') or contains(text(), 'Logout') or contains(@href, 'logout')]",
                timeout=5,
            )
            logout_btn.click()
            # Nếu có confirm dialog hoặc form, submit tiếp
            time.sleep(0.5)
            try:
                self.browser.find_element(By.CSS_SELECTOR, "[type='submit']").click()
            except Exception:
                pass
        except Exception:
            # Fallback: submit form logout bằng JavaScript
            self.browser.execute_script("""
                var form = document.createElement('form');
                form.method = 'POST';
                form.action = '/system/users/logout/';
                var csrf = document.querySelector('[name=csrfmiddlewaretoken]');
                if (csrf) { form.appendChild(csrf.cloneNode()); }
                document.body.appendChild(form);
                form.submit();
            """)

    # ─────────────────────────────────────────
    # Helper: Assertions tiện ích
    # ─────────────────────────────────────────

    def assert_page_contains(self, text: str):
        """Kiểm tra trang hiện tại chứa text."""
        body_text = self.browser.find_element(By.TAG_NAME, "body").text
        self.assertIn(text, body_text, f"Không tìm thấy '{text}' trên trang")

    def assert_current_url_contains(self, partial_url: str):
        """Kiểm tra URL hiện tại chứa chuỗi."""
        self.assertIn(
            partial_url,
            self.browser.current_url,
            f"URL '{self.browser.current_url}' không chứa '{partial_url}'",
        )

    def take_screenshot(self, name: str):
        """Chụp screenshot thủ công."""
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        filename = SCREENSHOT_DIR / f"{name}_{timestamp}.png"
        self.browser.save_screenshot(str(filename))
        print(f"📸 Screenshot: {filename}")
        return filename
