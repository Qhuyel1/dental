from pathlib import Path
from tempfile import TemporaryDirectory

from django.contrib.auth.models import Group, User
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.clinic.models import Staff, Patient

from .models import DatabaseBackup, SecurityEvent, get_user_security_profile


class UserManagementViewTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username="admin",
            password="StrongPass123!",
            is_staff=True,
            is_superuser=True,
        )
        self.client.login(username="admin", password="StrongPass123!")

    def test_user_list_renders_for_staff_user(self):
        response = self.client.get(reverse("users:user-list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Quản lý người dùng")

    def test_user_list_shows_linked_staff_profile_info(self):
        linked_user = User.objects.create_user(
            username="doctor-linked",
            password="StrongPass123!",
            email="doctor-linked@example.com",
            is_staff=True,
        )
        Staff.objects.create(
            employee_code="BS-UI-001",
            role=Staff.Role.DOCTOR,
            full_name="Bac Si Lien Ket",
            user=linked_user,
        )

        response = self.client.get(reverse("users:user-list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Bac Si Lien Ket")
        self.assertContains(response, "BS-UI-001")
        self.assertContains(response, "Bác sĩ")

    def test_user_list_filters_by_account_type(self):
        staff_user = User.objects.create_user(username="staff-u", password="StrongPass123!")
        Staff.objects.create(employee_code="BS-T-001", role=Staff.Role.DOCTOR, full_name="Staff Account", user=staff_user)

        patient_user = User.objects.create_user(username="patient-u", password="StrongPass123!")
        Patient.objects.create(patient_code="BN-T-001", full_name="Patient Account", user=patient_user)

        # Test filtering for staff
        response = self.client.get(reverse("users:user-list"), {"type": "staff"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "staff-u")
        self.assertNotContains(response, "patient-u")

        # Test filtering for patient
        response = self.client.get(reverse("users:user-list"), {"type": "patient"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "patient-u")
        self.assertNotContains(response, "staff-u")

        # Test filtering for unlinked
        response = self.client.get(reverse("users:user-list"), {"type": "unlinked"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "admin")
        self.assertNotContains(response, "staff-u")
        self.assertNotContains(response, "patient-u")

    def test_create_user_saves_groups_and_staff_flag(self):
        group, _ = Group.objects.get_or_create(name="Lễ tân")

        response = self.client.post(
            reverse("users:user-create"),
            {
                "username": "reception",
                "first_name": "Le",
                "last_name": "Tan",
                "email": "reception@example.com",
                "password1": "StrongPass123!",
                "password2": "StrongPass123!",
                "is_active": "on",
                "is_staff": "on",
                "groups": [str(group.pk)],
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        created_user = User.objects.get(username="reception")
        self.assertTrue(created_user.is_staff)
        self.assertTrue(created_user.groups.filter(pk=group.pk).exists())

    def test_non_staff_user_is_forbidden(self):
        self.client.logout()
        User.objects.create_user(username="normal", password="StrongPass123!")
        self.client.login(username="normal", password="StrongPass123!")

        response = self.client.get(reverse("users:user-list"))

        self.assertEqual(response.status_code, 403)

    def test_login_view_records_success_event(self):
        self.client.logout()

        response = self.client.post(
            reverse("users:login"),
            {"username": "admin", "password": "StrongPass123!"},
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            SecurityEvent.objects.filter(
                action=SecurityEvent.Action.LOGIN_SUCCESS,
                username="admin",
            ).exists()
        )

    def test_password_change_records_event(self):
        response = self.client.post(
            reverse("users:password-change"),
            {
                "old_password": "StrongPass123!",
                "new_password1": "StrongPass456!",
                "new_password2": "StrongPass456!",
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.check_password("StrongPass456!"))
        self.assertTrue(
            SecurityEvent.objects.filter(
                action=SecurityEvent.Action.PASSWORD_CHANGE,
                actor=self.admin,
            ).exists()
        )

    def test_login_with_temporary_password_redirects_to_password_change(self):
        self.client.logout()
        user = User.objects.create_user(
            username="temporary-user",
            password="StrongPass123!",
            is_staff=True,
        )
        profile = get_user_security_profile(user)
        profile.must_change_password = True
        profile.save(update_fields=["must_change_password", "updated_at"])

        response = self.client.post(
            reverse("users:login"),
            {"username": "temporary-user", "password": "StrongPass123!"},
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], reverse("users:password-change"))

        response = self.client.get(reverse("clinic:dashboard"))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], reverse("users:password-change"))

    def test_password_change_clears_temporary_password_flag(self):
        profile = get_user_security_profile(self.admin)
        profile.must_change_password = True
        profile.save(update_fields=["must_change_password", "updated_at"])

        response = self.client.post(
            reverse("users:password-change"),
            {
                "old_password": "StrongPass123!",
                "new_password1": "StrongPass456!",
                "new_password2": "StrongPass456!",
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        profile.refresh_from_db()
        self.assertFalse(profile.must_change_password)

    def test_staff_user_can_reset_temporary_password(self):
        user = User.objects.create_user(
            username="reset-target",
            password="StrongPass123!",
            is_staff=True,
            is_active=False,
        )

        response = self.client.post(
            reverse("users:user-reset-password", kwargs={"pk": user.pk}),
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        user.refresh_from_db()
        self.assertTrue(user.is_active)
        profile = get_user_security_profile(user)
        self.assertTrue(profile.must_change_password)
        self.assertContains(response, "Mật khẩu tạm thời mới")
        self.assertContains(response, user.username)

    def test_backup_create_records_file_and_event(self):
        with TemporaryDirectory() as tempdir, override_settings(BACKUP_ROOT=Path(tempdir)):
            response = self.client.post(reverse("users:backup-list"), follow=True)

            self.assertEqual(response.status_code, 200)
            backup = DatabaseBackup.objects.get()
            self.assertTrue(backup.absolute_path.exists())
            self.assertGreater(backup.size_bytes, 0)
            self.assertTrue(
                SecurityEvent.objects.filter(
                    action=SecurityEvent.Action.BACKUP_CREATED,
                    target_object_id=str(backup.pk),
                ).exists()
            )
