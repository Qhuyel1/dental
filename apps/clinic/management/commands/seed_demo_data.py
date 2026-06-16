from datetime import time, timedelta
from decimal import Decimal

from django.contrib.auth.models import Group, User
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.users.roles import (
    ROLE_ADMIN,
    ROLE_ASSISTANT,
    ROLE_CASHIER,
    ROLE_DOCTOR,
    ROLE_MANAGER,
    ROLE_RECEPTIONIST,
    ROLE_STOCK,
    sync_role_groups,
)
from apps.clinic.models import (
    Appointment,
    ClinicHoliday,
    DoctorSchedule,
    Patient,
    PriceList,
    Service,
    ServiceCategory,
    ServicePrice,
    Staff,
    Supply,
    SupplyLot,
    WorkShift,
)
from apps.payroll.models import (
    SalaryConfig,
    AppointmentComplexity,
    PaySlip,
    PaySlipEntry,
)

class Command(BaseCommand):
    help = "Seed demo data for the dental management web app."

    def handle(self, *args, **options):
        with transaction.atomic():
            self.seed_auth()
            staff = self.seed_staff()
            patients = self.seed_patients()
            services = self.seed_services()
            self.seed_price_list(services)
            self.seed_inventory()
            shifts = self.seed_work_shifts()
            schedules = self.seed_doctor_schedules(staff, shifts)
            self.seed_holidays()
            self.seed_appointments(patients, services, schedules)
            self.seed_payroll()

        self.stdout.write(self.style.SUCCESS("Đã tạo/cập nhật dữ liệu mẫu."))
        self.stdout.write("Tài khoản đăng nhập mẫu: demo_admin / Demo@12345")

    def seed_auth(self):
        sync_role_groups()
        groups = [ROLE_ADMIN, ROLE_MANAGER, ROLE_RECEPTIONIST, ROLE_DOCTOR, ROLE_ASSISTANT, ROLE_CASHIER, ROLE_STOCK]
        for group_name in groups:
            Group.objects.get_or_create(name=group_name)

        user, created = User.objects.get_or_create(
            username="demo_admin",
            defaults={
                "first_name": "Demo",
                "last_name": "Admin",
                "email": "demo_admin@example.com",
                "is_staff": True,
                "is_superuser": True,
                "is_active": True,
            },
        )
        user.first_name = "Demo"
        user.last_name = "Admin"
        user.email = "demo_admin@example.com"
        user.is_staff = True
        user.is_superuser = True
        user.is_active = True
        user.set_password("Demo@12345")
        user.save()
        user.groups.set(Group.objects.filter(name__in=groups))
        return created

    def seed_staff(self):
        staff_rows = [
            {
                "employee_code": "DEMO-BS-001",
                "role": Staff.Role.DOCTOR,
                "full_name": "BS. Nguyễn Minh An",
                "date_of_birth": "1984-03-12",
                "gender": Staff.Gender.MALE,
                "phone": "0901000001",
                "email": "minhan@demo-clinic.vn",
                "address": "Quận 1, TP.HCM",
                "primary_workplace": "Dental Management Clinic",
                "degree": "ThS.BS",
                "specialization": "Nha tổng quát, phục hình",
                "license_number": "CCHN-DEMO-001",
                "experience_years": 12,
                "start_date": "2021-01-04",
                "salary_coefficient": Decimal("1.50"),
                "emergency_contact_name": "Nguyễn Mai",
                "emergency_contact_phone": "0901999001",
            },
            {
                "employee_code": "DEMO-BS-002",
                "role": Staff.Role.DOCTOR,
                "full_name": "BS.CKI Trần Thu Hà",
                "date_of_birth": "1988-07-22",
                "gender": Staff.Gender.FEMALE,
                "phone": "0901000002",
                "email": "thuha@demo-clinic.vn",
                "address": "Quận 3, TP.HCM",
                "primary_workplace": "Dental Management Clinic",
                "degree": "BS.CKI",
                "specialization": "Chỉnh nha",
                "license_number": "CCHN-DEMO-002",
                "experience_years": 9,
                "start_date": "2022-02-14",
                "salary_coefficient": Decimal("1.30"),
                "emergency_contact_name": "Trần Minh",
                "emergency_contact_phone": "0901999002",
            },
            {
                "employee_code": "DEMO-BS-003",
                "role": Staff.Role.DOCTOR,
                "full_name": "BS. Lê Quốc Bảo",
                "date_of_birth": "1981-11-08",
                "gender": Staff.Gender.MALE,
                "phone": "0901000003",
                "email": "quocbao@demo-clinic.vn",
                "address": "Quận Bình Thạnh, TP.HCM",
                "primary_workplace": "Dental Management Clinic",
                "degree": "ThS.BS",
                "specialization": "Implant, tiểu phẫu",
                "license_number": "CCHN-DEMO-003",
                "experience_years": 15,
                "start_date": "2020-06-01",
                "salary_coefficient": Decimal("2.00"),
                "emergency_contact_name": "Lê Hạnh",
                "emergency_contact_phone": "0901999003",
            },
            {
                "employee_code": "DEMO-BS-004",
                "role": Staff.Role.DOCTOR,
                "full_name": "BS. Phạm Ngọc Linh",
                "date_of_birth": "1990-01-18",
                "gender": Staff.Gender.FEMALE,
                "phone": "0901000004",
                "email": "ngoclinh@demo-clinic.vn",
                "address": "TP. Thủ Đức, TP.HCM",
                "primary_workplace": "Dental Management Clinic",
                "degree": "BS",
                "specialization": "Nha khoa trẻ em, nội nha",
                "license_number": "CCHN-DEMO-004",
                "experience_years": 7,
                "start_date": "2023-03-20",
                "salary_coefficient": Decimal("1.30"),
                "emergency_contact_name": "Phạm Hưng",
                "emergency_contact_phone": "0901999004",
            },
            {
                "employee_code": "DEMO-NV-001",
                "role": Staff.Role.RECEPTIONIST,
                "full_name": "Võ Thị Mai",
                "date_of_birth": "1995-05-11",
                "gender": Staff.Gender.FEMALE,
                "phone": "0902000001",
                "email": "letan@demo-clinic.vn",
                "address": "Quận 10, TP.HCM",
                "primary_workplace": "Dental Management Clinic",
                "degree": "Cao đẳng điều dưỡng",
                "specialization": "Tiếp nhận và điều phối lịch hẹn",
                "experience_years": 5,
                "start_date": "2021-08-16",
            },
            {
                "employee_code": "DEMO-NV-002",
                "role": Staff.Role.ASSISTANT,
                "full_name": "Hoàng Văn Nam",
                "date_of_birth": "1994-09-04",
                "gender": Staff.Gender.MALE,
                "phone": "0902000002",
                "email": "trothu@demo-clinic.vn",
                "address": "Quận 5, TP.HCM",
                "primary_workplace": "Dental Management Clinic",
                "degree": "Chứng chỉ trợ thủ nha khoa",
                "specialization": "Hỗ trợ ghế nha, vô trùng dụng cụ",
                "experience_years": 6,
                "start_date": "2021-04-05",
            },
            {
                "employee_code": "DEMO-NV-003",
                "role": Staff.Role.MANAGER,
                "full_name": "Đặng Kim Chi",
                "date_of_birth": "1991-12-25",
                "gender": Staff.Gender.FEMALE,
                "phone": "0902000003",
                "email": "quanly@demo-clinic.vn",
                "address": "Quận Phú Nhuận, TP.HCM",
                "primary_workplace": "Dental Management Clinic",
                "degree": "Cử nhân quản trị",
                "specialization": "Quản lý vận hành phòng khám",
                "experience_years": 8,
                "start_date": "2020-02-03",
            },
        ]

        staff = {}
        for row in staff_rows:
            code = row.pop("employee_code")
            obj, _ = Staff.objects.update_or_create(employee_code=code, defaults={**row, "is_active": True})
            staff[code] = obj
        return staff

    def seed_patients(self):
        patient_rows = [
            {
                "patient_code": "DEMO-BN-001",
                "full_name": "Nguyễn Văn Hùng",
                "date_of_birth": "1986-02-15",
                "gender": Patient.Gender.MALE,
                "national_id": "079086000001",
                "phone": "0913000001",
                "email": "hung.nguyen@example.com",
                "address": "25 Nguyễn Trãi, Quận 1, TP.HCM",
                "occupation": "Kỹ sư phần mềm",
                "emergency_contact_name": "Nguyễn Thị Lan",
                "emergency_contact_phone": "0913999001",
                "blood_type": Patient.BloodType.O_POSITIVE,
                "medical_history": "Từng điều trị viêm nướu năm 2024.",
                "current_medications": "",
                "allergy_note": "Dị ứng penicillin.",
                "note": "Ưu tiên lịch buổi sáng.",
            },
            {
                "patient_code": "DEMO-BN-002",
                "full_name": "Trần Thị Lan",
                "date_of_birth": "1992-06-03",
                "gender": Patient.Gender.FEMALE,
                "national_id": "079192000002",
                "phone": "0913000002",
                "email": "lan.tran@example.com",
                "address": "42 Cách Mạng Tháng 8, Quận 3, TP.HCM",
                "occupation": "Nhân viên văn phòng",
                "emergency_contact_name": "Trần Văn Minh",
                "emergency_contact_phone": "0913999002",
                "blood_type": Patient.BloodType.A_POSITIVE,
                "medical_history": "",
                "current_medications": "",
                "allergy_note": "",
                "note": "Đang tư vấn chỉnh nha.",
            },
            {
                "patient_code": "DEMO-BN-003",
                "full_name": "Lê Minh Khoa",
                "date_of_birth": "1978-10-30",
                "gender": Patient.Gender.MALE,
                "national_id": "079078000003",
                "phone": "0913000003",
                "email": "khoa.le@example.com",
                "address": "18 Điện Biên Phủ, Bình Thạnh, TP.HCM",
                "occupation": "Kinh doanh",
                "emergency_contact_name": "Lê Bảo Anh",
                "emergency_contact_phone": "0913999003",
                "blood_type": Patient.BloodType.B_POSITIVE,
                "medical_history": "Tăng huyết áp nhẹ.",
                "current_medications": "Amlodipine 5mg",
                "allergy_note": "",
                "note": "Cần hỏi lại thuốc đang dùng trước tiểu phẫu.",
            },
            {
                "patient_code": "DEMO-BN-004",
                "full_name": "Phạm Gia Hân",
                "date_of_birth": "2014-04-21",
                "gender": Patient.Gender.FEMALE,
                "national_id": "",
                "phone": "0913000004",
                "email": "",
                "address": "9 Võ Văn Ngân, TP. Thủ Đức, TP.HCM",
                "occupation": "Học sinh",
                "emergency_contact_name": "Phạm Thu Trang",
                "emergency_contact_phone": "0913999004",
                "blood_type": "",
                "medical_history": "Sâu răng sữa.",
                "current_medications": "",
                "allergy_note": "",
                "note": "Phụ huynh đi cùng.",
            },
            {
                "patient_code": "DEMO-BN-005",
                "full_name": "Đỗ Quang Vinh",
                "date_of_birth": "1999-08-09",
                "gender": Patient.Gender.MALE,
                "national_id": "079099000005",
                "phone": "0913000005",
                "email": "vinh.do@example.com",
                "address": "73 Nguyễn Văn Cừ, Quận 5, TP.HCM",
                "occupation": "Sinh viên",
                "emergency_contact_name": "Đỗ Minh Tâm",
                "emergency_contact_phone": "0913999005",
                "blood_type": Patient.BloodType.AB_POSITIVE,
                "medical_history": "",
                "current_medications": "",
                "allergy_note": "Dị ứng hải sản.",
                "note": "Đã chụp phim răng khôn.",
            },
            {
                "patient_code": "DEMO-BN-006",
                "full_name": "Bùi Thảo Vy",
                "date_of_birth": "1996-12-17",
                "gender": Patient.Gender.FEMALE,
                "national_id": "079196000006",
                "phone": "0913000006",
                "email": "vy.bui@example.com",
                "address": "11 Lê Văn Sỹ, Phú Nhuận, TP.HCM",
                "occupation": "Thiết kế",
                "emergency_contact_name": "Bùi Hoàng",
                "emergency_contact_phone": "0913999006",
                "blood_type": Patient.BloodType.O_NEGATIVE,
                "medical_history": "",
                "current_medications": "",
                "allergy_note": "",
                "note": "Quan tâm tẩy trắng răng.",
            },
            {
                "patient_code": "DEMO-BN-007",
                "full_name": "Huỳnh Minh Đức",
                "date_of_birth": "1969-01-12",
                "gender": Patient.Gender.MALE,
                "national_id": "079069000007",
                "phone": "0913000007",
                "email": "duc.huynh@example.com",
                "address": "33 Âu Cơ, Tân Bình, TP.HCM",
                "occupation": "Nghỉ hưu",
                "emergency_contact_name": "Huỳnh Mai",
                "emergency_contact_phone": "0913999007",
                "blood_type": Patient.BloodType.B_NEGATIVE,
                "medical_history": "Đái tháo đường type 2.",
                "current_medications": "Metformin",
                "allergy_note": "",
                "note": "Cần kiểm tra đường huyết trước thủ thuật.",
            },
            {
                "patient_code": "DEMO-BN-008",
                "full_name": "Vũ Ngọc Anh",
                "date_of_birth": "2001-05-27",
                "gender": Patient.Gender.FEMALE,
                "national_id": "079101000008",
                "phone": "0913000008",
                "email": "ngocanh.vu@example.com",
                "address": "88 Pasteur, Quận 1, TP.HCM",
                "occupation": "Content creator",
                "emergency_contact_name": "Vũ Thanh",
                "emergency_contact_phone": "0913999008",
                "blood_type": "",
                "medical_history": "",
                "current_medications": "",
                "allergy_note": "",
                "note": "Đang theo dõi veneers.",
            },
            {
                "patient_code": "DEMO-BN-009",
                "full_name": "Cao Tuấn Kiệt",
                "date_of_birth": "1989-09-19",
                "gender": Patient.Gender.MALE,
                "national_id": "079089000009",
                "phone": "0913000009",
                "email": "kiet.cao@example.com",
                "address": "17 Nguyễn Hữu Cảnh, Bình Thạnh, TP.HCM",
                "occupation": "Tài xế",
                "emergency_contact_name": "Cao Hồng",
                "emergency_contact_phone": "0913999009",
                "blood_type": Patient.BloodType.A_NEGATIVE,
                "medical_history": "Viêm nha chu.",
                "current_medications": "",
                "allergy_note": "",
                "note": "Cần nhắc tái khám định kỳ.",
            },
            {
                "patient_code": "DEMO-BN-010",
                "full_name": "Mai Thanh Tâm",
                "date_of_birth": "1993-03-02",
                "gender": Patient.Gender.OTHER,
                "national_id": "079193000010",
                "phone": "0913000010",
                "email": "tam.mai@example.com",
                "address": "51 Nguyễn Thị Minh Khai, Quận 1, TP.HCM",
                "occupation": "Marketing",
                "emergency_contact_name": "Mai Thảo",
                "emergency_contact_phone": "0913999010",
                "blood_type": Patient.BloodType.AB_NEGATIVE,
                "medical_history": "",
                "current_medications": "",
                "allergy_note": "",
                "note": "Khách VIP.",
            },
        ]

        patients = {}
        for row in patient_rows:
            code = row.pop("patient_code")
            obj, _ = Patient.objects.update_or_create(patient_code=code, defaults={**row, "is_active": True})
            patients[code] = obj
        return patients

    def seed_services(self):
        category_rows = [
            ("DEMO-DM-001", "Khám và tư vấn", "Khám tổng quát, tư vấn kế hoạch điều trị."),
            ("DEMO-DM-002", "Điều trị răng", "Trám, điều trị tủy, nhổ răng thông thường."),
            ("DEMO-DM-003", "Chỉnh nha", "Tư vấn và điều trị chỉnh nha."),
            ("DEMO-DM-004", "Thẩm mỹ nha khoa", "Tẩy trắng, veneer, phục hình thẩm mỹ."),
            ("DEMO-DM-005", "Implant và tiểu phẫu", "Cấy ghép implant, nhổ răng khôn, tiểu phẫu."),
            ("DEMO-DM-006", "Nha khoa trẻ em", "Dịch vụ chăm sóc răng miệng trẻ em."),
        ]
        categories = {}
        for code, name, description in category_rows:
            categories[code], _ = ServiceCategory.objects.update_or_create(
                code=code,
                defaults={"name": name, "description": description, "is_active": True},
            )

        service_rows = [
            ("DEMO-DV-001", "DEMO-DM-001", "Khám răng tổng quát", 30, "Khám tổng quát tình trạng răng miệng."),
            ("DEMO-DV-002", "DEMO-DM-001", "Tư vấn kế hoạch điều trị", 45, "Tư vấn phác đồ và chi phí dự kiến."),
            ("DEMO-DV-003", "DEMO-DM-002", "Lấy cao răng", 45, "Làm sạch cao răng và đánh bóng."),
            ("DEMO-DV-004", "DEMO-DM-002", "Trám răng composite", 45, "Trám răng thẩm mỹ bằng composite."),
            ("DEMO-DV-005", "DEMO-DM-002", "Điều trị tủy một chân", 60, "Điều trị tủy răng một chân."),
            ("DEMO-DV-006", "DEMO-DM-002", "Nhổ răng thường", 45, "Nhổ răng không phẫu thuật."),
            ("DEMO-DV-007", "DEMO-DM-003", "Tư vấn chỉnh nha", 45, "Tư vấn niềng răng và khí cụ chỉnh nha."),
            ("DEMO-DV-008", "DEMO-DM-003", "Gắn mắc cài kim loại", 120, "Khởi động điều trị chỉnh nha mắc cài kim loại."),
            ("DEMO-DV-009", "DEMO-DM-004", "Tẩy trắng răng tại phòng khám", 90, "Tẩy trắng răng bằng đèn tại phòng khám."),
            ("DEMO-DV-010", "DEMO-DM-004", "Veneer sứ một răng", 90, "Phục hình veneer sứ thẩm mỹ."),
            ("DEMO-DV-011", "DEMO-DM-005", "Cấy ghép implant một trụ", 120, "Phẫu thuật đặt một trụ implant."),
            ("DEMO-DV-012", "DEMO-DM-005", "Nhổ răng khôn", 75, "Nhổ răng khôn có gây tê."),
            ("DEMO-DV-013", "DEMO-DM-006", "Khám răng trẻ em", 30, "Khám và hướng dẫn chăm sóc răng cho trẻ."),
            ("DEMO-DV-014", "DEMO-DM-006", "Trám răng sữa", 40, "Trám răng sữa sâu nhẹ."),
        ]
        services = {}
        for code, category_code, name, duration, description in service_rows:
            services[code], _ = Service.objects.update_or_create(
                code=code,
                defaults={
                    "category": categories[category_code],
                    "name": name,
                    "description": description,
                    "duration_minutes": duration,
                    "is_active": True,
                },
            )
        return services

    def seed_price_list(self, services):
        current_price_list, _ = PriceList.objects.update_or_create(
            name="DEMO - Bảng giá hiện hành 2026",
            defaults={
                "effective_from": timezone.localdate().replace(month=1, day=1),
                "effective_to": None,
                "is_active": True,
                "note": "Bảng giá mẫu dùng để test giao diện.",
            },
        )
        old_price_list, _ = PriceList.objects.update_or_create(
            name="DEMO - Bảng giá cũ 2025",
            defaults={
                "effective_from": timezone.localdate().replace(year=2025, month=1, day=1),
                "effective_to": timezone.localdate().replace(year=2025, month=12, day=31),
                "is_active": False,
                "note": "Bảng giá cũ để test lọc hết hạn/ngưng áp dụng.",
            },
        )

        prices = {
            "DEMO-DV-001": 150000,
            "DEMO-DV-002": 250000,
            "DEMO-DV-003": 350000,
            "DEMO-DV-004": 600000,
            "DEMO-DV-005": 1200000,
            "DEMO-DV-006": 500000,
            "DEMO-DV-007": 300000,
            "DEMO-DV-008": 7000000,
            "DEMO-DV-009": 1800000,
            "DEMO-DV-010": 6500000,
            "DEMO-DV-011": 18000000,
            "DEMO-DV-012": 2500000,
            "DEMO-DV-013": 120000,
            "DEMO-DV-014": 400000,
        }
        for service_code, price in prices.items():
            ServicePrice.objects.update_or_create(
                price_list=current_price_list,
                service=services[service_code],
                defaults={"price": Decimal(price), "note": "Giá mẫu hiện hành"},
            )
            ServicePrice.objects.update_or_create(
                price_list=old_price_list,
                service=services[service_code],
                defaults={"price": Decimal(int(price * 0.9)), "note": "Giá mẫu năm 2025"},
            )

    def seed_inventory(self):
        today = timezone.localdate()
        supply_rows = [
            {
                "code": "DEMO-VT-001",
                "name": "Găng tay nitrile",
                "category": Supply.Category.CONSUMABLE,
                "unit": "hộp",
                "minimum_quantity": Decimal("10"),
                "description": "Găng tay dùng trong khám và điều trị.",
                "lot_number": "GT-2026-01",
                "supplier": "Demo Medical",
                "quantity": Decimal("80"),
                "unit_cost": Decimal("95000"),
                "expiry_date": today.replace(year=today.year + 2),
            },
            {
                "code": "DEMO-VT-002",
                "name": "Kim tiêm nha khoa 27G",
                "category": Supply.Category.INJECTION,
                "unit": "hộp",
                "minimum_quantity": Decimal("5"),
                "description": "Kim tiêm dùng khi gây tê nha khoa.",
                "lot_number": "KTI-2026-02",
                "supplier": "Demo Dental Supply",
                "quantity": Decimal("30"),
                "unit_cost": Decimal("120000"),
                "expiry_date": today.replace(year=today.year + 1),
            },
            {
                "code": "DEMO-VT-003",
                "name": "Thuốc tê Lidocaine 2%",
                "category": Supply.Category.MEDICINE,
                "unit": "ống",
                "minimum_quantity": Decimal("20"),
                "description": "Thuốc tê dùng trong thủ thuật nha khoa.",
                "lot_number": "LIDO-2026-03",
                "supplier": "Demo Pharma",
                "quantity": Decimal("100"),
                "unit_cost": Decimal("18000"),
                "expiry_date": today + timedelta(days=45),
            },
            {
                "code": "DEMO-VT-004",
                "name": "Composite A2",
                "category": Supply.Category.RESTORATIVE,
                "unit": "tuýp",
                "minimum_quantity": Decimal("8"),
                "description": "Vật liệu trám răng thẩm mỹ màu A2.",
                "lot_number": "COM-A2-2026",
                "supplier": "Demo Dental Material",
                "quantity": Decimal("6"),
                "unit_cost": Decimal("320000"),
                "expiry_date": today.replace(year=today.year + 1),
            },
            {
                "code": "DEMO-VT-005",
                "name": "Dung dịch sát khuẩn bề mặt",
                "category": Supply.Category.STERILIZATION,
                "unit": "chai",
                "minimum_quantity": Decimal("6"),
                "description": "Dùng vệ sinh bề mặt ghế nha và khu vực điều trị.",
                "lot_number": "SK-2026-01",
                "supplier": "Demo Hygiene",
                "quantity": Decimal("24"),
                "unit_cost": Decimal("85000"),
                "expiry_date": today + timedelta(days=25),
            },
        ]

        for row in supply_rows:
            code = row.pop("code")
            lot_number = row.pop("lot_number")
            supplier = row.pop("supplier")
            quantity = row.pop("quantity")
            unit_cost = row.pop("unit_cost")
            expiry_date = row.pop("expiry_date")
            supply, _ = Supply.objects.update_or_create(
                supply_code=code,
                defaults={**row, "is_active": True},
            )
            SupplyLot.objects.update_or_create(
                supply=supply,
                lot_number=lot_number,
                defaults={
                    "supplier": supplier,
                    "received_date": today,
                    "expiry_date": expiry_date,
                    "initial_quantity": quantity,
                    "unit_cost": unit_cost,
                    "note": "Dữ liệu mẫu cho chức năng quản lý kho.",
                },
            )

    def seed_work_shifts(self):
        shifts = {}
        weekday_values = [
            WorkShift.Weekday.MONDAY,
            WorkShift.Weekday.TUESDAY,
            WorkShift.Weekday.WEDNESDAY,
            WorkShift.Weekday.THURSDAY,
            WorkShift.Weekday.FRIDAY,
            WorkShift.Weekday.SATURDAY,
        ]
        for weekday in weekday_values:
            coeff = Decimal("1.20") if weekday == WorkShift.Weekday.SATURDAY else Decimal("1.00")
            morning, _ = WorkShift.objects.update_or_create(
                weekday=weekday,
                name="DEMO Ca sáng",
                defaults={
                    "start_time": time(8, 0),
                    "end_time": time(12, 0),
                    "shift_coefficient": coeff,
                    "is_active": True,
                    "note": "Ca sáng mẫu",
                },
            )
            afternoon, _ = WorkShift.objects.update_or_create(
                weekday=weekday,
                name="DEMO Ca chiều",
                defaults={
                    "start_time": time(13, 30),
                    "end_time": time(17, 30),
                    "shift_coefficient": coeff,
                    "is_active": True,
                    "note": "Ca chiều mẫu",
                },
            )
            shifts[(weekday, "morning")] = morning
            shifts[(weekday, "afternoon")] = afternoon
        return shifts

    def seed_doctor_schedules(self, staff, shifts):
        today = timezone.localdate()
        week_start = today - timedelta(days=today.weekday())
        doctors = [
            staff["DEMO-BS-001"],
            staff["DEMO-BS-002"],
            staff["DEMO-BS-003"],
            staff["DEMO-BS-004"],
        ]
        schedules = {}
        for day_offset in range(0, 6):
            work_date = week_start + timedelta(days=day_offset)
            weekday = work_date.weekday()
            for doctor in doctors:
                for shift_key in ["morning", "afternoon"]:
                    shift = shifts[(weekday, shift_key)]
                    schedule, _ = DoctorSchedule.objects.update_or_create(
                        doctor=doctor,
                        work_date=work_date,
                        shift=shift,
                        defaults={"status": DoctorSchedule.Status.REGISTERED, "note": "Lịch trực mẫu"},
                    )
                    schedules[(doctor.employee_code, work_date, shift_key)] = schedule

        next_week = week_start + timedelta(days=7)
        for day_offset in range(0, 6):
            work_date = next_week + timedelta(days=day_offset)
            weekday = work_date.weekday()
            for doctor in doctors[:3]:
                shift = shifts[(weekday, "morning")]
                schedule, _ = DoctorSchedule.objects.update_or_create(
                    doctor=doctor,
                    work_date=work_date,
                    shift=shift,
                    defaults={"status": DoctorSchedule.Status.REGISTERED, "note": "Lịch trực tuần sau"},
                )
                schedules[(doctor.employee_code, work_date, "next_morning")] = schedule

        return schedules

    def seed_holidays(self):
        today = timezone.localdate()
        rows = [
            (today + timedelta(days=10), "DEMO - Nghỉ bảo trì thiết bị", "Phòng khám bảo trì ghế nha số 2."),
            (today + timedelta(days=30), "DEMO - Nghỉ đào tạo nội bộ", "Đào tạo quy trình tiếp nhận bệnh nhân."),
        ]
        for holiday_date, name, note in rows:
            ClinicHoliday.objects.update_or_create(
                date=holiday_date,
                defaults={"name": name, "note": note, "is_active": True},
            )

    def seed_appointments(self, patients, services, schedules):
        today = timezone.localdate()
        week_start = today - timedelta(days=today.weekday())
        monday = week_start
        tuesday = week_start + timedelta(days=1)
        wednesday = week_start + timedelta(days=2)
        thursday = week_start + timedelta(days=3)
        friday = week_start + timedelta(days=4)
        saturday = week_start + timedelta(days=5)
        next_monday = week_start + timedelta(days=7)

        rows = [
            (
                "DEMO-LH-001",
                patients["DEMO-BN-001"],
                schedules[("DEMO-BS-001", monday, "morning")],
                services["DEMO-DV-001"],
                time(8, 0),
                time(8, 30),
                Appointment.Status.COMPLETED,
                "Khám tổng quát định kỳ",
            ),
            (
                "DEMO-LH-002",
                patients["DEMO-BN-002"],
                schedules[("DEMO-BS-002", monday, "afternoon")],
                services["DEMO-DV-007"],
                time(14, 0),
                time(14, 45),
                Appointment.Status.CONFIRMED,
                "Tư vấn chỉnh nha",
            ),
            (
                "DEMO-LH-003",
                patients["DEMO-BN-003"],
                schedules[("DEMO-BS-003", tuesday, "morning")],
                services["DEMO-DV-012"],
                time(9, 0),
                time(10, 15),
                Appointment.Status.SCHEDULED,
                "Đau răng khôn hàm dưới",
            ),
            (
                "DEMO-LH-004",
                patients["DEMO-BN-004"],
                schedules[("DEMO-BS-004", tuesday, "afternoon")],
                services["DEMO-DV-013"],
                time(15, 0),
                time(15, 30),
                Appointment.Status.CHECKED_IN,
                "Khám răng trẻ em",
            ),
            (
                "DEMO-LH-005",
                patients["DEMO-BN-005"],
                schedules[("DEMO-BS-001", wednesday, "morning")],
                services["DEMO-DV-003"],
                time(8, 30),
                time(9, 15),
                Appointment.Status.CONFIRMED,
                "Lấy cao răng",
            ),
            (
                "DEMO-LH-006",
                patients["DEMO-BN-006"],
                schedules[("DEMO-BS-002", wednesday, "afternoon")],
                services["DEMO-DV-009"],
                time(13, 30),
                time(15, 0),
                Appointment.Status.SCHEDULED,
                "Tẩy trắng răng",
            ),
            (
                "DEMO-LH-007",
                patients["DEMO-BN-007"],
                schedules[("DEMO-BS-003", thursday, "morning")],
                services["DEMO-DV-011"],
                time(10, 0),
                time(12, 0),
                Appointment.Status.SCHEDULED,
                "Tư vấn implant",
            ),
            (
                "DEMO-LH-008",
                patients["DEMO-BN-008"],
                schedules[("DEMO-BS-004", thursday, "afternoon")],
                services["DEMO-DV-010"],
                time(14, 30),
                time(16, 0),
                Appointment.Status.CONFIRMED,
                "Tư vấn veneer",
            ),
            (
                "DEMO-LH-009",
                patients["DEMO-BN-009"],
                schedules[("DEMO-BS-001", friday, "morning")],
                services["DEMO-DV-005"],
                time(9, 30),
                time(10, 30),
                Appointment.Status.NO_SHOW,
                "Điều trị tủy",
            ),
            (
                "DEMO-LH-010",
                patients["DEMO-BN-010"],
                schedules[("DEMO-BS-002", friday, "afternoon")],
                services["DEMO-DV-004"],
                time(16, 0),
                time(16, 45),
                Appointment.Status.CANCELLED,
                "Trám răng composite",
            ),
            (
                "DEMO-LH-011",
                patients["DEMO-BN-004"],
                schedules[("DEMO-BS-003", saturday, "morning")],
                services["DEMO-DV-014"],
                time(8, 30),
                time(9, 10),
                Appointment.Status.SCHEDULED,
                "Trám răng sữa",
            ),
            (
                "DEMO-LH-012",
                patients["DEMO-BN-001"],
                schedules[("DEMO-BS-004", saturday, "afternoon")],
                services["DEMO-DV-006"],
                time(15, 30),
                time(16, 15),
                Appointment.Status.CONFIRMED,
                "Nhổ răng thường",
            ),
            (
                "DEMO-LH-013",
                patients["DEMO-BN-002"],
                schedules[("DEMO-BS-001", next_monday, "next_morning")],
                services["DEMO-DV-008"],
                time(9, 0),
                time(11, 0),
                Appointment.Status.SCHEDULED,
                "Gắn mắc cài",
            ),
        ]

        for code, patient, schedule, service, start, end, status, complaint in rows:
            Appointment.objects.update_or_create(
                appointment_code=code,
                defaults={
                    "patient": patient,
                    "doctor_schedule": schedule,
                    "service": service,
                    "start_time": start,
                    "end_time": end,
                    "status": status,
                    "chief_complaint": complaint,
                    "note": "Dữ liệu mẫu để kiểm thử giao diện.",
                },
            )

    def seed_payroll(self):
        self.stdout.write("Seeding payroll demo data...")
        
        # Clear existing payroll data
        PaySlip.objects.all().delete()
        SalaryConfig.objects.all().delete()
        AppointmentComplexity.objects.all().delete()
        
        # 1. Salary Configurations
        config_2025 = SalaryConfig.objects.create(
            hourly_rate=Decimal("120000"),
            effective_from=timezone.localdate().replace(year=2025, month=1, day=1),
            note="Lương cơ bản năm 2025"
        )
        config_2026 = SalaryConfig.objects.create(
            hourly_rate=Decimal("150000"),
            effective_from=timezone.localdate().replace(year=2026, month=1, day=1),
            note="Lương cơ bản năm 2026 (áp dụng hiện tại)"
        )
        
        # 2. Appointment Complexities for some existing completed appointments
        completed_apps = Appointment.objects.filter(status=Appointment.Status.COMPLETED)[:5]
        complexities = [Decimal("0.10"), Decimal("0.20"), Decimal("0.30"), Decimal("0.15"), Decimal("0.25")]
        notes = ["Điều trị tủy phức tạp", "Bệnh nhân có bệnh nền huyết áp", "Nhổ răng khôn mọc lệch độ 3", "Lấy cao răng nhiều vôi", "Chỉnh nha khớp cắn ngược"]
        
        for idx, app in enumerate(completed_apps):
            if idx < len(complexities):
                AppointmentComplexity.objects.get_or_create(
                    appointment=app,
                    defaults={
                        "complexity_coefficient": complexities[idx],
                        "note": notes[idx]
                    }
                )
                
        # 3. Create historical PaySlips for April (PAID) and May (CONFIRMED) 2026
        doctors = Staff.objects.filter(role=Staff.Role.DOCTOR)
        admin_user = User.objects.filter(is_superuser=True).first()
        
        import random
        random.seed(42)
        
        for doctor in doctors:
            for month, status in [(4, PaySlip.Status.PAID), (5, PaySlip.Status.CONFIRMED)]:
                # Base snapshot fields
                hourly_rate = config_2026.hourly_rate
                doc_coeff = doctor.salary_coefficient or Decimal("1.30")
                
                payslip = PaySlip.objects.create(
                    doctor=doctor,
                    month=month,
                    year=2026,
                    hourly_rate=hourly_rate,
                    doctor_coefficient=doc_coeff,
                    status=status,
                    note=f"Phiếu lương mẫu tháng {month}/2026",
                    created_by=admin_user
                )
                
                # Fetch first 4 schedules to create entries
                schedules = DoctorSchedule.objects.filter(doctor=doctor)[:4]
                
                for idx, sched in enumerate(schedules):
                    shift_hours = Decimal("4.0000") # 4 hours per shift
                    shift_coeff = sched.shift.shift_coefficient or Decimal("1.00")
                    patient_coeff = Decimal(str(random.choice([0.00, 0.10, 0.20, 0.30])))
                    
                    entry = PaySlipEntry(
                        payslip=payslip,
                        doctor_schedule=sched,
                        shift_hours=shift_hours,
                        shift_coefficient=shift_coeff,
                        patient_coefficient_total=patient_coeff,
                    )
                    entry.compute()
                    entry.save()
                    
                payslip.recalculate()
