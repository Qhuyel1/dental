from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from apps.clinic.models import Patient


class PortalSessionTests(TestCase):
    def setUp(self):
        self.patient_user = User.objects.create_user(
            username="patient1",
            password="Password123!",
        )
        self.patient = Patient.objects.create(
            patient_code="BN-000001",
            full_name="Bệnh Nhân Test",
            user=self.patient_user,
        )
        self.admin_user = User.objects.create_user(
            username="admin1",
            password="Password123!",
            is_staff=True,
            is_superuser=True,
        )

    def test_portal_login_uses_patient_session_cookie(self):
        self.client.cookies.clear()
        
        response = self.client.post(
            reverse("portal:login"),
            {"username": "patient1", "password": "Password123!"},
            follow=True
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("patient_sessionid", self.client.cookies)
        self.assertNotIn("sessionid", self.client.cookies)

    def test_system_login_uses_default_session_cookie(self):
        self.client.cookies.clear()
        
        response = self.client.post(
            reverse("users:login"),
            {"username": "admin1", "password": "Password123!"},
            follow=True
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("sessionid", self.client.cookies)
        self.assertNotIn("patient_sessionid", self.client.cookies)

    def test_portal_and_system_sessions_coexist(self):
        # Login as admin
        self.client.post(
            reverse("users:login"),
            {"username": "admin1", "password": "Password123!"},
        )
        self.assertIn("sessionid", self.client.cookies)
        admin_cookie = self.client.cookies["sessionid"].value

        # Login as patient
        self.client.post(
            reverse("portal:login"),
            {"username": "patient1", "password": "Password123!"},
        )
        self.assertIn("patient_sessionid", self.client.cookies)
        patient_cookie = self.client.cookies["patient_sessionid"].value

        self.assertNotEqual(admin_cookie, patient_cookie)

    def test_unauthenticated_portal_redirects_to_portal_login(self):
        response = self.client.get(reverse("portal:home"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("portal:login"), response["Location"])

    def test_authenticated_patient_can_access_portal(self):
        self.client.post(
            reverse("portal:login"),
            {"username": "patient1", "password": "Password123!"},
        )
        response = self.client.get(reverse("portal:home"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Tổng quan")

    def test_patient_portal_logout(self):
        self.client.post(
            reverse("portal:login"),
            {"username": "patient1", "password": "Password123!"},
        )
        self.assertIn("patient_sessionid", self.client.cookies)
        
        # Post to logout
        response = self.client.post(
            reverse("portal:logout"),
            follow=True
        )
        self.assertEqual(response.status_code, 200)
        # The session should be empty/deleted
        session_cookie = self.client.cookies.get("patient_sessionid")
        self.assertTrue(session_cookie is None or session_cookie.value == "")


from apps.portal.models import Conversation, Message
from apps.clinic.models import Staff

class PortalMessagingTests(TestCase):
    def setUp(self):
        # Create Patient
        self.patient_user = User.objects.create_user(
            username="patient1",
            password="Password123!",
        )
        self.patient = Patient.objects.create(
            patient_code="BN-000001",
            full_name="Bệnh Nhân Test",
            user=self.patient_user,
        )

        # Create Staff
        self.staff_user = User.objects.create_user(
            username="staff1",
            password="Password123!",
            is_staff=True,
        )
        self.staff = Staff.objects.create(
            employee_code="NV-000001",
            full_name="Nhân Viên Test",
            user=self.staff_user,
            role="receptionist"
        )
        
        # Another Patient (for access control test)
        self.patient_user2 = User.objects.create_user(
            username="patient2",
            password="Password123!",
        )
        self.patient2 = Patient.objects.create(
            patient_code="BN-000002",
            full_name="Bệnh Nhân Test 2",
            user=self.patient_user2,
        )

    def test_patient_can_create_conversation(self):
        self.client.post(
            reverse("portal:login"),
            {"username": "patient1", "password": "Password123!"},
        )
        # Create conversation
        response = self.client.post(
            reverse("portal:messages-create"),
            {"subject": "Cần hỗ trợ về lịch hẹn", "content": "Tôi muốn đổi lịch hẹn ngày mai."},
            follow=True
        )
        self.assertEqual(response.status_code, 200)
        
        # Verify db
        conv = Conversation.objects.filter(patient=self.patient).first()
        self.assertIsNotNone(conv)
        self.assertEqual(conv.subject, "Cần hỗ trợ về lịch hẹn")
        self.assertEqual(conv.messages.count(), 1)
        self.assertEqual(conv.messages.first().content, "Tôi muốn đổi lịch hẹn ngày mai.")

    def test_patient_can_send_and_poll_message(self):
        self.client.post(
            reverse("portal:login"),
            {"username": "patient1", "password": "Password123!"},
        )
        # Setup conversation
        conv = Conversation.objects.create(patient=self.patient, subject="Test Subject")
        msg = Message.objects.create(conversation=conv, sender=self.patient_user, content="Initial message")

        # Send new message via AJAX
        response = self.client.post(
            reverse("portal:messages-send", kwargs={"pk": conv.pk}),
            {"content": "Tin nhắn mới từ bệnh nhân"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest"
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("id", data)
        self.assertEqual(data["content"], "Tin nhắn mới từ bệnh nhân")

        # Poll messages
        response = self.client.get(
            reverse("portal:messages-poll", kwargs={"pk": conv.pk}),
            {"after_id": msg.pk},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest"
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data["messages"]), 1)
        self.assertEqual(data["messages"][0]["content"], "Tin nhắn mới từ bệnh nhân")

    def test_patient_cannot_access_others_conversation(self):
        # Log in as patient 2
        self.client.post(
            reverse("portal:login"),
            {"username": "patient2", "password": "Password123!"},
        )
        # Create a conversation belonging to patient 1
        conv = Conversation.objects.create(patient=self.patient, subject="Test Subject")

        # Try to view detail
        response = self.client.get(reverse("portal:messages-detail", kwargs={"pk": conv.pk}))
        self.assertEqual(response.status_code, 404)

        # Try to send message
        response = self.client.post(
            reverse("portal:messages-send", kwargs={"pk": conv.pk}),
            {"content": "Hack"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest"
        )
        self.assertEqual(response.status_code, 404)

    def test_patient_can_close_conversation(self):
        self.client.post(
            reverse("portal:login"),
            {"username": "patient1", "password": "Password123!"},
        )
        conv = Conversation.objects.create(patient=self.patient, subject="Test Subject")
        
        response = self.client.post(
            reverse("portal:messages-close", kwargs={"pk": conv.pk}),
            follow=True
        )
        self.assertEqual(response.status_code, 200)
        conv.refresh_from_db()
        self.assertTrue(conv.is_closed)


class StaffMessagingTests(TestCase):
    def setUp(self):
        # Create Patient
        self.patient_user = User.objects.create_user(
            username="patient1",
            password="Password123!",
        )
        self.patient = Patient.objects.create(
            patient_code="BN-000001",
            full_name="Bệnh Nhân Test",
            user=self.patient_user,
        )

        # Create Staff (with superuser bypass or proper group/permission, is_superuser is easiest)
        self.staff_user = User.objects.create_user(
            username="staff1",
            password="Password123!",
            is_staff=True,
            is_superuser=True,
        )
        self.staff = Staff.objects.create(
            employee_code="NV-000001",
            full_name="Nhân Viên Test",
            user=self.staff_user,
            role="receptionist"
        )
        
        self.conv = Conversation.objects.create(patient=self.patient, subject="Hỗ trợ thanh toán")
        self.msg = Message.objects.create(conversation=self.conv, sender=self.patient_user, content="Tôi cần hóa đơn")

    def test_staff_can_view_conversation_list_and_detail(self):
        self.client.post(
            reverse("users:login"),
            {"username": "staff1", "password": "Password123!"},
        )
        response = self.client.get(reverse("clinic:conversation-list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Hỗ trợ thanh toán")

        response = self.client.get(reverse("clinic:conversation-detail", kwargs={"pk": self.conv.pk}))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Tôi cần hóa đơn")

    def test_staff_can_assign_self_to_conversation(self):
        self.client.post(
            reverse("users:login"),
            {"username": "staff1", "password": "Password123!"},
        )
        self.assertIsNone(self.conv.assigned_staff)
        
        response = self.client.post(
            reverse("clinic:conversation-assign", kwargs={"pk": self.conv.pk}),
            follow=True
        )
        self.assertEqual(response.status_code, 200)
        self.conv.refresh_from_db()
        self.assertEqual(self.conv.assigned_staff, self.staff)

    def test_staff_can_reply_and_poll_message(self):
        self.client.post(
            reverse("users:login"),
            {"username": "staff1", "password": "Password123!"},
        )
        # Reply
        response = self.client.post(
            reverse("clinic:conversation-send", kwargs={"pk": self.conv.pk}),
            {"content": "Tôi sẽ hỗ trợ bạn ngay"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest"
        )
        self.assertEqual(response.status_code, 200)
        
        # Check DB
        self.assertEqual(self.conv.messages.count(), 2)
        reply = self.conv.messages.last()
        self.assertEqual(reply.sender, self.staff_user)
        self.assertEqual(reply.content, "Tôi sẽ hỗ trợ bạn ngay")

        # Poll messages
        response = self.client.get(
            reverse("clinic:conversation-poll", kwargs={"pk": self.conv.pk}),
            {"after_id": self.msg.pk},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest"
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data["messages"]), 1)
        self.assertEqual(data["messages"][0]["content"], "Tôi sẽ hỗ trợ bạn ngay")

    def test_staff_can_close_conversation(self):
        self.client.post(
            reverse("users:login"),
            {"username": "staff1", "password": "Password123!"},
        )
        response = self.client.post(
            reverse("clinic:conversation-close", kwargs={"pk": self.conv.pk}),
            follow=True
        )
        self.assertEqual(response.status_code, 200)
        self.conv.refresh_from_db()
        self.assertTrue(self.conv.is_closed)

