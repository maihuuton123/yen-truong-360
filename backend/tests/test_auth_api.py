import tempfile
import unittest
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core import security
from app.api.v1.admin import deadline_input_to_utc_naive, deadline_status_out
from app.core.config import settings
from app.core.security import hash_password
from app.db.base import Base
from app.db.dependencies import get_db
from app.main import create_app
from app.models import (
    AdditionalInfoRequest,
    AdditionalInfoRequestStatus,
    Area,
    Attachment,
    AuditLog,
    Category,
    Department,
    DuplicateLinkStatus,
    Report,
    ReportAssignmentHistory,
    ReportInternalNote,
    ReportPriority,
    ReportDuplicateLink,
    ReportSourceBlock,
    ReportStatus,
    StatusHistory,
    User,
)

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 24


class AuthApiTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        database_path = Path(self.temp_dir.name) / "test.db"
        self.engine = create_engine(f"sqlite:///{database_path}", connect_args={"check_same_thread": False})
        self.SessionTesting = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        Base.metadata.create_all(bind=self.engine)
        self.seed_users()

        self.previous_secret = settings.auth_secret_key
        self.previous_expiration = settings.auth_token_expire_seconds
        self.previous_upload_dir = settings.upload_dir
        self.previous_public_site_url = settings.public_site_url
        settings.auth_secret_key = "unit-test-secret-key-change-me"
        settings.auth_token_expire_seconds = 900
        settings.upload_dir = str(Path(self.temp_dir.name) / "uploads")
        settings.public_site_url = "https://thefour.top"
        security.reset_revoked_tokens()

        app = create_app()
        app.dependency_overrides[get_db] = self.override_get_db
        self.app = app
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        self.engine.dispose()
        settings.auth_secret_key = self.previous_secret
        settings.auth_token_expire_seconds = self.previous_expiration
        settings.upload_dir = self.previous_upload_dir
        settings.public_site_url = self.previous_public_site_url
        security.reset_revoked_tokens()
        self.temp_dir.cleanup()

    def override_get_db(self):
        db = self.SessionTesting()
        try:
            yield db
        finally:
            db.close()

    def seed_users(self):
        with self.SessionTesting() as db:
            category = Category(name="Giao thông – vật cản", icon="traffic", display_order=1, is_active=True)
            category_2 = Category(name="Nguy cơ cháy, nổ", icon="fire", display_order=2, is_active=True)
            area = Area(name="Khu vực demo 1", display_order=1, is_active=True)
            area_2 = Area(name="Khu vực demo 2", display_order=2, is_active=True)
            db.add_all([category, category_2, area, area_2])
            db.flush()
            self.category_id = category.id
            self.category_2_id = category_2.id
            self.area_id = area.id
            self.area_2_id = area_2.id
            db.add_all(
                [
                    User(
                        username="admin",
                        password_hash=hash_password("admin-password"),
                        full_name="Admin",
                        role="ADMIN",
                        is_active=True,
                    ),
                    User(
                        username="receiver",
                        password_hash=hash_password("receiver-password"),
                        full_name="Receiver",
                        role="RECEIVER",
                        is_active=True,
                    ),
                    User(
                        username="handler",
                        password_hash=hash_password("handler-password"),
                        full_name="Handler",
                        role="HANDLER",
                        is_active=True,
                    ),
                    User(
                        username="inactive",
                        password_hash=hash_password("inactive-password"),
                        full_name="Inactive",
                        role="ADMIN",
                        is_active=False,
                    ),
                    Report(
                        tracking_code="YT360-AAAAAA",
                        category_id=category.id,
                        area_id=area.id,
                        description="Phản ánh mới.",
                        status=ReportStatus.NEW,
                    ),
                    Report(
                        tracking_code="YT360-BBBBBB",
                        category_id=category.id,
                        area_id=area.id,
                        description="Đang phối hợp.",
                        status=ReportStatus.COORDINATING,
                    ),
                    Report(
                        tracking_code="YT360-CCCCCC",
                        category_id=category.id,
                        area_id=area.id,
                        description="Đã xử lý.",
                        status=ReportStatus.RESOLVED,
                    ),
                    Report(
                        tracking_code="YT360-DDDDDD",
                        category_id=category_2.id,
                        area_id=area_2.id,
                        description="Đã tiếp nhận.",
                        status=ReportStatus.RECEIVED,
                    ),
                ]
            )
            db.flush()
            report = db.query(Report).filter(Report.tracking_code == "YT360-AAAAAA").one()
            db.add(
                Attachment(
                    report_id=report.id,
                    stored_filename="missing-test-image.png",
                    original_filename="test-image.png",
                    mime_type="image/png",
                    file_size=12,
                )
            )
            db.commit()

    def login(self, username="admin", password="admin-password"):
        return self.client.post("/api/auth/login", json={"username": username, "password": password})

    def auth_headers(self, username="admin", password="admin-password"):
        response = self.login(username, password)
        self.assertEqual(response.status_code, 200)
        return {"Authorization": f"Bearer {response.json()['access_token']}"}

    def report_id(self, tracking_code):
        with self.SessionTesting() as db:
            return db.query(Report).filter(Report.tracking_code == tracking_code).one().id

    def user_id(self, username):
        with self.SessionTesting() as db:
            return db.query(User).filter(User.username == username).one().id

    def assign_report_to_user(self, tracking_code, username="handler"):
        user_id = self.user_id(username)
        with self.SessionTesting() as db:
            report = db.query(Report).filter(Report.tracking_code == tracking_code).one()
            report.assigned_to = user_id
            db.commit()
            return report.id

    def test_login_success_returns_token_and_user_without_password_hash(self):
        response = self.login()

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["token_type"], "bearer")
        self.assertIn("access_token", body)
        self.assertEqual(body["expires_in"], 900)
        self.assertEqual(body["user"]["username"], "admin")
        self.assertEqual(body["user"]["role"], "ADMIN")
        self.assertNotIn("password", response.text.lower())
        self.assertNotIn("password_hash", response.text.lower())

    def test_login_wrong_password_fails(self):
        response = self.login(password="wrong-password")

        self.assertEqual(response.status_code, 401)
        self.assertNotIn("password_hash", response.text.lower())

    def test_login_inactive_user_fails(self):
        response = self.login("inactive", "inactive-password")

        self.assertEqual(response.status_code, 401)

    def test_protected_endpoint_requires_authentication(self):
        response = self.client.get("/api/admin/dashboard")

        self.assertEqual(response.status_code, 401)

    def test_invalid_token_is_rejected(self):
        response = self.client.get("/api/admin/dashboard", headers={"Authorization": "Bearer not-a-token"})

        self.assertEqual(response.status_code, 401)

    def test_expired_token_is_rejected(self):
        settings.auth_token_expire_seconds = -1
        response = self.login()
        self.assertEqual(response.status_code, 200)
        token = response.json()["access_token"]

        response = self.client.get("/api/admin/dashboard", headers={"Authorization": f"Bearer {token}"})

        self.assertEqual(response.status_code, 401)

    def test_logout_revokes_token(self):
        headers = self.auth_headers()

        self.assertEqual(self.client.get("/api/admin/dashboard", headers=headers).status_code, 200)
        self.assertEqual(self.client.post("/api/auth/logout", headers=headers).status_code, 204)
        self.assertEqual(self.client.get("/api/admin/dashboard", headers=headers).status_code, 401)

    def test_dashboard_returns_report_cards_and_work_summary(self):
        response = self.client.get("/api/admin/dashboard", headers=self.auth_headers())

        self.assertEqual(response.status_code, 200)
        body = response.json()
        cards = {card["key"]: card["value"] for card in body["cards"]}
        self.assertEqual(cards["new"], 1)
        self.assertEqual(cards["coordinating"], 1)
        self.assertEqual(cards["resolved"], 1)
        self.assertEqual(cards["total"], 4)
        self.assertEqual(body["work"]["new_reports"], 1)
        self.assertEqual(body["work"]["coordinating_reports"], 1)
        self.assertEqual(body["work"]["needs_update"], 2)
        self.assertEqual(body["work"]["deadline_due_soon"], 0)
        self.assertEqual(body["work"]["deadline_overdue"], 0)

    def test_deadline_status_boundaries_and_timezone_conversion(self):
        fixed_now = datetime(2026, 10, 12, 8, 0, tzinfo=timezone.utc)

        self.assertEqual(
            deadline_status_out(
                Report(
                    tracking_code="YT360-ONTRAK",
                    category_id=self.category_id,
                    description="Con han.",
                    deadline_at=fixed_now + timedelta(hours=25),
                    status=ReportStatus.NEW,
                ),
                now=fixed_now,
            ).code,
            "ON_TRACK",
        )
        self.assertEqual(
            deadline_status_out(
                Report(
                    tracking_code="YT360-DUESON",
                    category_id=self.category_id,
                    description="Dung han.",
                    deadline_at=fixed_now,
                    status=ReportStatus.NEW,
                ),
                now=fixed_now,
            ).code,
            "DUE_SOON",
        )
        self.assertEqual(
            deadline_status_out(
                Report(
                    tracking_code="YT360-OVERDU",
                    category_id=self.category_id,
                    description="Qua han.",
                    deadline_at=fixed_now - timedelta(seconds=1),
                    status=ReportStatus.NEW,
                ),
                now=fixed_now,
            ).code,
            "OVERDUE",
        )
        self.assertEqual(
            deadline_status_out(
                Report(
                    tracking_code="YT360-DONEOK",
                    category_id=self.category_id,
                    description="Hoan thanh dung han.",
                    deadline_at=fixed_now,
                    status=ReportStatus.RESOLVED,
                    status_history=[
                        StatusHistory(
                            new_status=ReportStatus.RESOLVED,
                            created_at=fixed_now,
                        )
                    ],
                ),
                now=fixed_now,
            ).code,
            "COMPLETED_ON_TIME",
        )
        self.assertEqual(
            deadline_status_out(
                Report(
                    tracking_code="YT360-DONELT",
                    category_id=self.category_id,
                    description="Hoan thanh sau han.",
                    deadline_at=fixed_now - timedelta(minutes=1),
                    status=ReportStatus.RESOLVED,
                    status_history=[
                        StatusHistory(
                            new_status=ReportStatus.RESOLVED,
                            created_at=fixed_now,
                        )
                    ],
                ),
                now=fixed_now,
            ).code,
            "COMPLETED_LATE",
        )
        self.assertEqual(
            deadline_input_to_utc_naive(datetime(2026, 10, 12, 8, 30)),
            datetime(2026, 10, 12, 1, 30),
        )

    def test_deadline_time_windows_cover_v26_required_boundaries(self):
        fixed_now = datetime(2026, 2, 28, 17, 0, tzinfo=timezone.utc)
        cases = [
            ("NO_DEADLINE", None, "NO_DEADLINE"),
            ("SEVEN_DAYS", fixed_now + timedelta(days=7), "ON_TRACK"),
            ("THREE_DAYS", fixed_now + timedelta(days=3), "ON_TRACK"),
            ("TWENTY_FOUR_HOURS", fixed_now + timedelta(hours=24), "DUE_SOON"),
            ("TWELVE_HOURS", fixed_now + timedelta(hours=12), "DUE_SOON"),
            ("ONE_HOUR", fixed_now + timedelta(hours=1), "DUE_SOON"),
            ("ONE_MINUTE", fixed_now + timedelta(minutes=1), "DUE_SOON"),
            ("EXACT_DEADLINE", fixed_now, "DUE_SOON"),
            ("OVERDUE_ONE_MINUTE", fixed_now - timedelta(minutes=1), "OVERDUE"),
            ("OVERDUE_ONE_HOUR", fixed_now - timedelta(hours=1), "OVERDUE"),
            ("OVERDUE_ONE_DAY", fixed_now - timedelta(days=1), "OVERDUE"),
            ("OVERDUE_SEVEN_DAYS", fixed_now - timedelta(days=7), "OVERDUE"),
            ("LEAP_DAY", datetime(2028, 2, 29, 0, 0, tzinfo=timezone.utc), "ON_TRACK"),
            ("YEAR_ROLLOVER", datetime(2027, 1, 1, 0, 0, tzinfo=timezone.utc), "ON_TRACK"),
        ]
        for tracking_suffix, deadline_at, expected_code in cases:
            with self.subTest(tracking_suffix=tracking_suffix):
                status_out = deadline_status_out(
                    Report(
                        tracking_code=f"YT360-{tracking_suffix[:6]}",
                        category_id=self.category_id,
                        description="Boundary check.",
                        deadline_at=deadline_at,
                        status=ReportStatus.NEW,
                    ),
                    now=fixed_now,
                )
                self.assertEqual(status_out.code, expected_code)
                if deadline_at is not None:
                    self.assertEqual(
                        status_out.remaining_seconds,
                        int((deadline_at - fixed_now).total_seconds()),
                    )

    def test_dashboard_my_work_and_filters_include_deadline_management(self):
        handler_id = self.user_id("handler")
        now = datetime.now(timezone.utc).replace(microsecond=0)
        with self.SessionTesting() as db:
            db.query(Report).filter(Report.tracking_code == "YT360-AAAAAA").update(
                {
                    Report.assigned_to: handler_id,
                    Report.deadline_at: (now + timedelta(hours=30)).replace(tzinfo=None),
                }
            )
            db.query(Report).filter(Report.tracking_code == "YT360-BBBBBB").update(
                {
                    Report.assigned_to: handler_id,
                    Report.deadline_at: (now + timedelta(hours=12)).replace(tzinfo=None),
                }
            )
            db.query(Report).filter(Report.tracking_code == "YT360-DDDDDD").update(
                {
                    Report.assigned_to: handler_id,
                    Report.deadline_at: (now - timedelta(hours=2)).replace(tzinfo=None),
                }
            )
            db.query(Report).filter(Report.tracking_code == "YT360-CCCCCC").update(
                {
                    Report.assigned_to: handler_id,
                    Report.deadline_at: (now - timedelta(days=1)).replace(tzinfo=None),
                }
            )
            completed_late = db.query(Report).filter(Report.tracking_code == "YT360-CCCCCC").one()
            db.add(
                StatusHistory(
                    report_id=completed_late.id,
                    new_status=ReportStatus.RESOLVED,
                    created_at=now.replace(tzinfo=None),
                )
            )
            completed_on_time = Report(
                tracking_code="YT360-DONEON",
                category_id=self.category_id,
                area_id=self.area_id,
                description="Hoan thanh dung han.",
                status=ReportStatus.RESOLVED,
                assigned_to=handler_id,
                deadline_at=(now + timedelta(hours=1)).replace(tzinfo=None),
            )
            db.add(completed_on_time)
            db.flush()
            db.add(
                StatusHistory(
                    report_id=completed_on_time.id,
                    new_status=ReportStatus.RESOLVED,
                    created_at=now.replace(tzinfo=None),
                )
            )
            db.commit()

        dashboard = self.client.get("/api/admin/dashboard", headers=self.auth_headers()).json()
        self.assertEqual(dashboard["work"]["deadline_on_track"], 1)
        self.assertEqual(dashboard["work"]["deadline_due_soon"], 1)
        self.assertEqual(dashboard["work"]["deadline_overdue"], 1)
        self.assertEqual(dashboard["work"]["deadline_completed"], 2)
        self.assertEqual(dashboard["work"]["deadline_completed_on_time"], 1)
        self.assertEqual(dashboard["work"]["deadline_completed_late"], 1)
        self.assertEqual(dashboard["work"]["deadline_total"], 5)

        due_soon = self.client.get(
            "/api/admin/reports",
            params={"deadline_status": "DUE_SOON", "sort_by": "deadline_at", "sort_order": "asc"},
            headers=self.auth_headers(),
        )
        overdue = self.client.get(
            "/api/admin/reports",
            params={"deadline_status": "OVERDUE"},
            headers=self.auth_headers(),
        )
        completed_late = self.client.get(
            "/api/admin/reports",
            params={"deadline_status": "COMPLETED_LATE"},
            headers=self.auth_headers(),
        )
        my_work = self.client.get(
            "/api/admin/reports/my-work",
            params={"deadline_status": "DUE_SOON"},
            headers=self.auth_headers("handler", "handler-password"),
        )

        self.assertEqual(due_soon.status_code, 200)
        self.assertEqual(due_soon.json()["total"], 1)
        self.assertEqual(due_soon.json()["items"][0]["deadline_status"]["code"], "DUE_SOON")
        self.assertEqual(overdue.status_code, 200)
        self.assertEqual(overdue.json()["items"][0]["deadline_status"]["code"], "OVERDUE")
        self.assertEqual(completed_late.status_code, 200)
        self.assertEqual(completed_late.json()["total"], 1)
        self.assertEqual(completed_late.json()["items"][0]["deadline_status"]["code"], "COMPLETED_LATE")
        self.assertEqual(my_work.status_code, 200)
        self.assertEqual(my_work.json()["total"], 1)
        self.assertIsNotNone(my_work.json()["items"][0]["deadline_at"])
        self.assertEqual(my_work.json()["items"][0]["deadline_status"]["code"], "DUE_SOON")

    def test_admin_qr_uses_public_site_url_and_can_download_svg(self):
        headers = self.auth_headers("admin", "admin-password")

        response = self.client.get("/api/admin/qr", headers=headers)

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["target_url"], "https://thefour.top")
        self.assertIn("<svg", body["svg"])
        self.assertIn("https://thefour.top", body["svg"])
        self.assertNotIn("localhost", body["svg"])

        download = self.client.get("/api/admin/qr/download", headers=headers)
        self.assertEqual(download.status_code, 200)
        self.assertIn("image/svg+xml", download.headers["content-type"])
        self.assertEqual(download.headers["cache-control"], "no-store")
        self.assertIn("YenTruong360_QR.svg", download.headers["content-disposition"])
        self.assertIn("https://thefour.top", download.text)

    def test_admin_qr_requires_admin_role(self):
        self.assertEqual(self.client.get("/api/admin/qr").status_code, 401)
        self.assertEqual(
            self.client.get("/api/admin/qr", headers=self.auth_headers("receiver", "receiver-password")).status_code,
            403,
        )
        self.assertEqual(
            self.client.get("/api/admin/qr/download", headers=self.auth_headers("handler", "handler-password")).status_code,
            403,
        )

    def test_admin_can_create_update_disable_category_with_audit_log(self):
        headers = self.auth_headers("admin", "admin-password")

        created = self.client.post(
            "/api/admin/categories",
            json={"name": "  Thu gom rac  ", "icon": "trash", "is_active": True, "display_order": 7},
            headers=headers,
        )

        self.assertEqual(created.status_code, 201)
        category_id = created.json()["id"]
        self.assertEqual(created.json()["name"], "Thu gom rac")
        self.assertEqual(created.json()["icon"], "trash")
        self.assertEqual(created.json()["display_order"], 7)
        self.assertTrue(created.json()["is_active"])
        self.assertEqual(created.json()["report_count"], 0)
        public_categories = self.client.get("/api/public/categories").json()
        self.assertIn(category_id, [item["id"] for item in public_categories])

        updated = self.client.put(
            f"/api/admin/categories/{category_id}",
            json={"name": "Thu gom rac cap nhat", "icon": "clean", "is_active": False, "display_order": 2},
            headers=headers,
        )

        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.json()["name"], "Thu gom rac cap nhat")
        self.assertFalse(updated.json()["is_active"])
        self.assertEqual(updated.json()["display_order"], 2)
        public_categories = self.client.get("/api/public/categories").json()
        self.assertNotIn(category_id, [item["id"] for item in public_categories])
        with self.SessionTesting() as db:
            actions = [
                item.action
                for item in db.query(AuditLog)
                .filter(AuditLog.entity_type == "category", AuditLog.entity_id == category_id)
                .order_by(AuditLog.id)
                .all()
            ]
            self.assertEqual(actions, ["CATEGORY_CREATE", "CATEGORY_UPDATE"])

    def test_admin_can_create_update_disable_area_with_audit_log(self):
        headers = self.auth_headers("admin", "admin-password")

        created = self.client.post(
            "/api/admin/areas",
            json={"name": "  Thon 3  ", "is_active": True, "display_order": 5},
            headers=headers,
        )

        self.assertEqual(created.status_code, 201)
        area_id = created.json()["id"]
        self.assertEqual(created.json()["name"], "Thon 3")
        self.assertEqual(created.json()["report_count"], 0)
        public_areas = self.client.get("/api/public/areas").json()
        self.assertIn(area_id, [item["id"] for item in public_areas])

        updated = self.client.put(
            f"/api/admin/areas/{area_id}",
            json={"name": "Thon 3 cap nhat", "is_active": False, "display_order": 1},
            headers=headers,
        )

        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.json()["name"], "Thon 3 cap nhat")
        self.assertFalse(updated.json()["is_active"])
        public_areas = self.client.get("/api/public/areas").json()
        self.assertNotIn(area_id, [item["id"] for item in public_areas])
        with self.SessionTesting() as db:
            actions = [
                item.action
                for item in db.query(AuditLog)
                .filter(AuditLog.entity_type == "area", AuditLog.entity_id == area_id)
                .order_by(AuditLog.id)
                .all()
            ]
            self.assertEqual(actions, ["AREA_CREATE", "AREA_UPDATE"])

    def test_catalog_management_requires_admin_role(self):
        receiver_headers = self.auth_headers("receiver", "receiver-password")
        handler_headers = self.auth_headers("handler", "handler-password")

        self.assertEqual(self.client.get("/api/admin/categories", headers=receiver_headers).status_code, 403)
        self.assertEqual(
            self.client.post(
                "/api/admin/areas",
                json={"name": "Khong du quyen", "is_active": True, "display_order": 1},
                headers=handler_headers,
            ).status_code,
            403,
        )

    def test_admin_can_manage_assignment_departments_with_audit_log(self):
        headers = self.auth_headers("admin", "admin-password")

        created = self.client.post(
            "/api/admin/departments",
            json={"name": "  To ha tang  ", "is_active": True, "display_order": 3},
            headers=headers,
        )

        self.assertEqual(created.status_code, 201)
        department_id = created.json()["id"]
        self.assertEqual(created.json()["name"], "To ha tang")
        self.assertEqual(created.json()["report_count"], 0)

        visible_to_handler = self.client.get(
            "/api/admin/departments",
            headers=self.auth_headers("handler", "handler-password"),
        )
        self.assertEqual(visible_to_handler.status_code, 200)
        self.assertIn(department_id, [item["id"] for item in visible_to_handler.json()])

        updated = self.client.put(
            f"/api/admin/departments/{department_id}",
            json={"name": "To ha tang cap nuoc", "is_active": False, "display_order": 4},
            headers=headers,
        )
        duplicate = self.client.post(
            "/api/admin/departments",
            json={"name": "To ha tang cap nuoc", "is_active": True, "display_order": 5},
            headers=headers,
        )
        forbidden = self.client.post(
            "/api/admin/departments",
            json={"name": "Cong an xa", "is_active": True, "display_order": 6},
            headers=self.auth_headers("receiver", "receiver-password"),
        )

        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.json()["name"], "To ha tang cap nuoc")
        self.assertFalse(updated.json()["is_active"])
        self.assertEqual(duplicate.status_code, 409)
        self.assertEqual(forbidden.status_code, 403)
        with self.SessionTesting() as db:
            department = db.query(Department).filter(Department.id == department_id).one()
            actions = [
                item.action
                for item in db.query(AuditLog)
                .filter(AuditLog.entity_type == "department", AuditLog.entity_id == department_id)
                .order_by(AuditLog.id)
                .all()
            ]
            self.assertEqual(department.display_order, 4)
            self.assertEqual(actions, ["DEPARTMENT_CREATE", "DEPARTMENT_UPDATE"])

    def test_catalog_duplicate_names_are_rejected(self):
        headers = self.auth_headers("admin", "admin-password")
        with self.SessionTesting() as db:
            existing_category_name = db.get(Category, self.category_id).name
            existing_area_name = db.get(Area, self.area_id).name

        duplicate_category = self.client.post(
            "/api/admin/categories",
            json={"name": existing_category_name, "icon": "x", "is_active": True, "display_order": 9},
            headers=headers,
        )
        duplicate_area = self.client.post(
            "/api/admin/areas",
            json={"name": existing_area_name, "is_active": True, "display_order": 9},
            headers=headers,
        )

        self.assertEqual(duplicate_category.status_code, 409)
        self.assertEqual(duplicate_area.status_code, 409)

    def test_soft_disabled_referenced_catalog_items_keep_report_integrity(self):
        headers = self.auth_headers("admin", "admin-password")

        category_response = self.client.put(
            f"/api/admin/categories/{self.category_id}",
            json={"name": "Giao thÃ´ng â€“ váº­t cáº£n", "icon": "traffic", "is_active": False, "display_order": 1},
            headers=headers,
        )
        area_response = self.client.put(
            f"/api/admin/areas/{self.area_id}",
            json={"name": "Khu vá»±c demo 1", "is_active": False, "display_order": 1},
            headers=headers,
        )

        self.assertEqual(category_response.status_code, 200)
        self.assertEqual(area_response.status_code, 200)
        self.assertEqual(category_response.json()["report_count"], 3)
        self.assertEqual(area_response.json()["report_count"], 3)
        self.assertNotIn(self.category_id, [item["id"] for item in self.client.get("/api/public/categories").json()])
        self.assertNotIn(self.area_id, [item["id"] for item in self.client.get("/api/public/areas").json()])
        report_response = self.client.get(
            "/api/admin/reports",
            params={"category_id": self.category_id, "area_id": self.area_id},
            headers=headers,
        )
        self.assertEqual(report_response.status_code, 200)
        self.assertEqual(report_response.json()["total"], 3)
        lookup_response = self.client.get("/api/public/reports/YT360-AAAAAA")
        self.assertEqual(lookup_response.status_code, 200)
        self.assertEqual(lookup_response.json()["category"], "Giao thÃ´ng â€“ váº­t cáº£n")
        self.assertEqual(lookup_response.json()["area"], "Khu vá»±c demo 1")

    def test_hard_delete_catalog_items_is_not_exposed(self):
        headers = self.auth_headers("admin", "admin-password")

        self.assertEqual(self.client.delete(f"/api/admin/categories/{self.category_id}", headers=headers).status_code, 405)
        self.assertEqual(self.client.delete(f"/api/admin/areas/{self.area_id}", headers=headers).status_code, 405)

    def test_admin_can_list_create_and_login_staff_users_without_hash_leak(self):
        headers = self.auth_headers("admin", "admin-password")

        list_response = self.client.get("/api/admin/users", headers=headers)
        self.assertEqual(list_response.status_code, 200)
        self.assertNotIn("password", list_response.text.lower())
        self.assertNotIn("password_hash", list_response.text.lower())

        created = self.client.post(
            "/api/admin/users",
            json={
                "username": "test_receiver_step9",
                "password": "Step9ReceiverStrong!123",
                "full_name": "Receiver Step 9",
                "role": "RECEIVER",
                "is_active": True,
            },
            headers=headers,
        )

        self.assertEqual(created.status_code, 201)
        body = created.json()
        self.assertEqual(body["username"], "test_receiver_step9")
        self.assertEqual(body["role"], "RECEIVER")
        self.assertNotIn("password", created.text.lower())
        self.assertNotIn("password_hash", created.text.lower())
        with self.SessionTesting() as db:
            user = db.query(User).filter(User.username == "test_receiver_step9").one()
            self.assertNotEqual(user.password_hash, "Step9ReceiverStrong!123")
            self.assertTrue(user.password_hash.startswith("pbkdf2_sha256$"))
            audit = db.query(AuditLog).filter(AuditLog.entity_type == "user", AuditLog.entity_id == user.id).one()
            self.assertEqual(audit.action, "USER_CREATE")
            self.assertNotIn("Step9ReceiverStrong", audit.details)
            self.assertNotIn("password", audit.details.lower())

        login_response = self.login("test_receiver_step9", "Step9ReceiverStrong!123")
        self.assertEqual(login_response.status_code, 200)
        self.assertEqual(login_response.json()["user"]["role"], "RECEIVER")

    def test_create_staff_users_for_all_step9_roles(self):
        headers = self.auth_headers("admin", "admin-password")
        users = [
            ("test_receiver_step9", "RECEIVER", "Step9ReceiverStrong!123"),
            ("test_handler_step9", "HANDLER", "Step9HandlerStrong!123"),
            ("test_admin_step9", "ADMIN", "Step9AdminStrong!123"),
        ]

        for username, role, password in users:
            response = self.client.post(
                "/api/admin/users",
                json={
                    "username": username,
                    "password": password,
                    "full_name": username.replace("_", " ").title(),
                    "role": role,
                    "is_active": True,
                },
                headers=headers,
            )
            self.assertEqual(response.status_code, 201)
            login_response = self.login(username, password)
            self.assertEqual(login_response.status_code, 200)
            self.assertEqual(login_response.json()["user"]["role"], role)

    def test_user_management_requires_admin_role(self):
        receiver_headers = self.auth_headers("receiver", "receiver-password")
        handler_headers = self.auth_headers("handler", "handler-password")

        self.assertEqual(self.client.get("/api/admin/users").status_code, 401)
        self.assertEqual(self.client.get("/api/admin/users", headers={"Authorization": "Bearer bad-token"}).status_code, 401)
        self.assertEqual(self.client.get("/api/admin/users", headers=receiver_headers).status_code, 403)
        self.assertEqual(
            self.client.post(
                "/api/admin/users",
                json={
                    "username": "blocked_handler",
                    "password": "Step9Blocked!123",
                    "full_name": "Blocked Handler",
                    "role": "HANDLER",
                    "is_active": True,
                },
                headers=handler_headers,
            ).status_code,
            403,
        )
        self.assertEqual(self.client.get("/api/admin/users", headers=self.auth_headers()).status_code, 200)

    def test_admin_can_list_audit_logs_without_sensitive_fields(self):
        admin_headers = self.auth_headers("admin", "admin-password")
        receiver_headers = self.auth_headers("receiver", "receiver-password")

        created = self.client.post(
            "/api/admin/categories",
            json={"name": "Audit category", "icon": "audit", "is_active": True, "display_order": 11},
            headers=admin_headers,
        )
        self.assertEqual(created.status_code, 201)

        no_auth = self.client.get("/api/admin/audit-logs")
        receiver = self.client.get("/api/admin/audit-logs", headers=receiver_headers)
        response = self.client.get("/api/admin/audit-logs", headers=admin_headers)

        self.assertEqual(no_auth.status_code, 401)
        self.assertEqual(receiver.status_code, 403)
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertGreaterEqual(body["total"], 1)
        self.assertEqual(body["page"], 1)
        self.assertEqual(body["page_size"], 20)
        first = body["items"][0]
        self.assertIn(
            first["action"],
            {"CATEGORY_CREATE", "AREA_CREATE", "USER_CREATE", "USER_UPDATE", "USER_PASSWORD_RESET", "REPORT_RECEIVE"},
        )
        self.assertIn("created_at", first)
        self.assertIn("user", first)
        self.assertNotIn("password_hash", response.text.lower())
        self.assertNotIn("admin-password", response.text.lower())
        self.assertNotIn("receiver-password", response.text.lower())

    def test_update_user_role_affects_new_login_and_backend_authorization(self):
        headers = self.auth_headers("admin", "admin-password")
        created = self.client.post(
            "/api/admin/users",
            json={
                "username": "test_receiver_step9",
                "password": "Step9ReceiverStrong!123",
                "full_name": "Receiver Step 9",
                "role": "RECEIVER",
                "is_active": True,
            },
            headers=headers,
        )
        user_id = created.json()["id"]

        updated = self.client.put(
            f"/api/admin/users/{user_id}",
            json={"full_name": "Handler Step 9", "role": "HANDLER", "is_active": True},
            headers=headers,
        )

        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.json()["role"], "HANDLER")
        login_response = self.login("test_receiver_step9", "Step9ReceiverStrong!123")
        self.assertEqual(login_response.status_code, 200)
        token = login_response.json()["access_token"]
        role_headers = {"Authorization": f"Bearer {token}"}
        self.assertEqual(self.client.get("/api/admin/handle-work", headers=role_headers).status_code, 200)
        self.assertEqual(self.client.get("/api/admin/receive-work", headers=role_headers).status_code, 403)
        with self.SessionTesting() as db:
            actions = [
                item.action
                for item in db.query(AuditLog)
                .filter(AuditLog.entity_type == "user", AuditLog.entity_id == user_id)
                .order_by(AuditLog.id)
            ]
            self.assertEqual(actions, ["USER_CREATE", "USER_UPDATE"])

    def test_disable_user_blocks_login_and_existing_token(self):
        headers = self.auth_headers("admin", "admin-password")
        created = self.client.post(
            "/api/admin/users",
            json={
                "username": "test_handler_step9",
                "password": "Step9HandlerStrong!123",
                "full_name": "Handler Step 9",
                "role": "HANDLER",
                "is_active": True,
            },
            headers=headers,
        )
        user_id = created.json()["id"]
        login_response = self.login("test_handler_step9", "Step9HandlerStrong!123")
        self.assertEqual(login_response.status_code, 200)
        old_token = login_response.json()["access_token"]

        disabled = self.client.put(
            f"/api/admin/users/{user_id}",
            json={"full_name": "Handler Step 9", "role": "HANDLER", "is_active": False},
            headers=headers,
        )

        self.assertEqual(disabled.status_code, 200)
        self.assertFalse(disabled.json()["is_active"])
        self.assertEqual(self.login("test_handler_step9", "Step9HandlerStrong!123").status_code, 401)
        self.assertEqual(
            self.client.get("/api/admin/dashboard", headers={"Authorization": f"Bearer {old_token}"}).status_code,
            401,
        )

    def test_reset_password_hashes_new_password_and_never_returns_hash(self):
        headers = self.auth_headers("admin", "admin-password")
        created = self.client.post(
            "/api/admin/users",
            json={
                "username": "test_admin_step9",
                "password": "Step9AdminStrong!123",
                "full_name": "Admin Step 9",
                "role": "ADMIN",
                "is_active": True,
            },
            headers=headers,
        )
        user_id = created.json()["id"]
        with self.SessionTesting() as db:
            old_hash = db.get(User, user_id).password_hash

        reset = self.client.post(
            f"/api/admin/users/{user_id}/password",
            json={"password": "Step9AdminNewStrong!456"},
            headers=headers,
        )

        self.assertEqual(reset.status_code, 200)
        self.assertNotIn("password_hash", reset.text.lower())
        self.assertEqual(self.login("test_admin_step9", "Step9AdminStrong!123").status_code, 401)
        self.assertEqual(self.login("test_admin_step9", "Step9AdminNewStrong!456").status_code, 200)
        with self.SessionTesting() as db:
            user = db.get(User, user_id)
            self.assertNotEqual(user.password_hash, old_hash)
            self.assertNotEqual(user.password_hash, "Step9AdminNewStrong!456")
            audit = (
                db.query(AuditLog)
                .filter(AuditLog.entity_type == "user", AuditLog.entity_id == user_id, AuditLog.action == "USER_PASSWORD_RESET")
                .one()
            )
            self.assertNotIn("Step9AdminNewStrong", audit.details)
            self.assertNotIn("password", audit.details.lower())

    def test_admin_cannot_self_lock_or_demote_last_admin(self):
        headers = self.auth_headers("admin", "admin-password")
        with self.SessionTesting() as db:
            admin_id = db.query(User).filter(User.username == "admin").one().id

        self_disable = self.client.put(
            f"/api/admin/users/{admin_id}",
            json={"full_name": "Admin", "role": "ADMIN", "is_active": False},
            headers=headers,
        )
        self_demote = self.client.put(
            f"/api/admin/users/{admin_id}",
            json={"full_name": "Admin", "role": "RECEIVER", "is_active": True},
            headers=headers,
        )

        self.assertEqual(self_disable.status_code, 409)
        self.assertEqual(self_demote.status_code, 409)

    def test_user_validation_rejects_bad_inputs_without_500(self):
        headers = self.auth_headers("admin", "admin-password")
        invalid_payloads = [
            {"username": "ab", "password": "Step9Strong!123", "full_name": "Bad", "role": "RECEIVER", "is_active": True},
            {"username": "bad space", "password": "Step9Strong!123", "full_name": "Bad", "role": "RECEIVER", "is_active": True},
            {"username": "bad_role", "password": "Step9Strong!123", "full_name": "Bad", "role": "ROOT", "is_active": True},
            {"username": "bad_password", "password": "short", "full_name": "Bad", "role": "RECEIVER", "is_active": True},
        ]

        for payload in invalid_payloads:
            response = self.client.post("/api/admin/users", json=payload, headers=headers)
            self.assertIn(response.status_code, {422})

        missing = self.client.put(
            "/api/admin/users/999999",
            json={"full_name": "Missing", "role": "HANDLER", "is_active": True},
            headers=headers,
        )
        bad_id = self.client.put(
            "/api/admin/users/not-an-id",
            json={"full_name": "Bad id", "role": "HANDLER", "is_active": True},
            headers=headers,
        )
        self.assertEqual(missing.status_code, 404)
        self.assertEqual(bad_id.status_code, 422)

    def test_admin_reports_filters_and_paginates_on_backend(self):
        response = self.client.get(
            "/api/admin/reports",
            params={"status": "COORDINATING", "page": 1, "page_size": 1},
            headers=self.auth_headers(),
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["total"], 1)
        self.assertEqual(body["page"], 1)
        self.assertEqual(body["page_size"], 1)
        self.assertEqual(body["items"][0]["tracking_code"], "YT360-BBBBBB")
        self.assertEqual(body["items"][0]["category"], "Giao thông – vật cản")
        self.assertEqual(body["items"][0]["area"], "Khu vực demo 1")

    def test_admin_reports_filters_by_tracking_code(self):
        response = self.client.get(
            "/api/admin/reports",
            params={"tracking_code": "YT360-DDDDDD"},
            headers=self.auth_headers(),
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["total"], 1)
        self.assertEqual(body["items"][0]["tracking_code"], "YT360-DDDDDD")

    def test_admin_reports_returns_empty_for_missing_tracking_code(self):
        response = self.client.get(
            "/api/admin/reports",
            params={"tracking_code": "YT360-ZZZZZZ"},
            headers=self.auth_headers(),
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["total"], 0)
        self.assertEqual(response.json()["items"], [])

    def test_admin_reports_filters_by_category_and_area(self):
        response = self.client.get(
            "/api/admin/reports",
            params={"category_id": self.category_2_id, "area_id": self.area_2_id},
            headers=self.auth_headers(),
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["total"], 1)
        self.assertEqual(body["items"][0]["tracking_code"], "YT360-DDDDDD")

    def test_admin_reports_filters_by_date_range(self):
        response = self.client.get(
            "/api/admin/reports",
            params={"from_date": "2000-01-01", "to_date": "2999-12-31"},
            headers=self.auth_headers(),
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["total"], 4)

    def test_admin_reports_pagination_has_no_overlap_between_pages(self):
        headers = self.auth_headers()
        page_1 = self.client.get("/api/admin/reports", params={"page": 1, "page_size": 2}, headers=headers)
        page_2 = self.client.get("/api/admin/reports", params={"page": 2, "page_size": 2}, headers=headers)

        self.assertEqual(page_1.status_code, 200)
        self.assertEqual(page_2.status_code, 200)
        page_1_codes = {item["tracking_code"] for item in page_1.json()["items"]}
        page_2_codes = {item["tracking_code"] for item in page_2.json()["items"]}
        self.assertEqual(page_1.json()["total"], 4)
        self.assertEqual(page_2.json()["total"], 4)
        self.assertFalse(page_1_codes & page_2_codes)

    def test_admin_reports_pagination_combines_with_status_filter(self):
        response = self.client.get(
            "/api/admin/reports",
            params={"status": "NEW", "page": 1, "page_size": 1},
            headers=self.auth_headers(),
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["total"], 1)
        self.assertEqual(body["items"][0]["status"], "NEW")

    def test_admin_report_detail_returns_description_attachments_and_history(self):
        report_id = self.report_id("YT360-AAAAAA")

        response = self.client.get(f"/api/admin/reports/{report_id}", headers=self.auth_headers())

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["id"], report_id)
        self.assertEqual(body["tracking_code"], "YT360-AAAAAA")
        self.assertTrue(body["description"])
        self.assertTrue(body["category"])
        self.assertTrue(body["area"])
        self.assertEqual(body["status"], "NEW")
        self.assertEqual(body["attachments"][0]["original_filename"], "test-image.png")
        self.assertEqual(body["attachments"][0]["attachment_type"], "INITIAL")
        self.assertFalse(body["attachments"][0]["is_public"])
        self.assertEqual(body["duplicate_links"], [])
        self.assertEqual(body["status_history"], [])

    def test_handler_reports_are_limited_to_assigned_reports(self):
        assigned_report_id = self.assign_report_to_user("YT360-AAAAAA")
        unassigned_report_id = self.report_id("YT360-BBBBBB")

        list_response = self.client.get(
            "/api/admin/reports",
            headers=self.auth_headers("handler", "handler-password"),
        )
        assigned_detail = self.client.get(
            f"/api/admin/reports/{assigned_report_id}",
            headers=self.auth_headers("handler", "handler-password"),
        )
        forbidden_detail = self.client.get(
            f"/api/admin/reports/{unassigned_report_id}",
            headers=self.auth_headers("handler", "handler-password"),
        )
        admin_detail = self.client.get(
            f"/api/admin/reports/{unassigned_report_id}",
            headers=self.auth_headers("admin", "admin-password"),
        )

        self.assertEqual(list_response.status_code, 200)
        self.assertEqual([item["id"] for item in list_response.json()["items"]], [assigned_report_id])
        self.assertEqual(assigned_detail.status_code, 200)
        self.assertEqual(forbidden_detail.status_code, 403)
        self.assertEqual(admin_detail.status_code, 200)

    def test_admin_can_link_related_reports_without_merging_originals(self):
        report_id = self.report_id("YT360-AAAAAA")
        related_report_id = self.report_id("YT360-BBBBBB")

        response = self.client.post(
            f"/api/admin/reports/{report_id}/related-reports",
            json={"related_report_id": related_report_id, "reason": "Same incident reported twice"},
            headers=self.auth_headers("handler", "handler-password"),
        )
        no_auth_response = self.client.post(
            f"/api/admin/reports/{report_id}/related-reports",
            json={"related_report_id": related_report_id},
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(no_auth_response.status_code, 401)
        body = response.json()
        self.assertEqual(body["related_report_id"], related_report_id)
        self.assertEqual(body["related_tracking_code"], "YT360-BBBBBB")
        self.assertEqual(body["status"], "LINKED")

        detail = self.client.get(f"/api/admin/reports/{report_id}", headers=self.auth_headers())
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.json()["duplicate_links"][0]["related_tracking_code"], "YT360-BBBBBB")
        with self.SessionTesting() as db:
            self.assertIsNotNone(db.get(Report, report_id))
            self.assertIsNotNone(db.get(Report, related_report_id))
            link = db.query(ReportDuplicateLink).one()
            self.assertEqual(link.status, DuplicateLinkStatus.LINKED)

    def test_related_report_link_rejects_self_link(self):
        report_id = self.report_id("YT360-AAAAAA")

        response = self.client.post(
            f"/api/admin/reports/{report_id}/related-reports",
            json={"related_report_id": report_id},
            headers=self.auth_headers(),
        )

        self.assertEqual(response.status_code, 422)

    def test_handler_can_upload_processing_images_but_receiver_cannot(self):
        report_id = self.assign_report_to_user("YT360-AAAAAA")

        response = self.client.post(
            f"/api/admin/reports/{report_id}/attachments",
            data={"attachment_type": "AFTER"},
            files=[
                ("images", ("after-1.png", PNG_BYTES, "image/png")),
                ("images", ("after-2.png", PNG_BYTES, "image/png")),
            ],
            headers=self.auth_headers("handler", "handler-password"),
        )
        receiver_response = self.client.post(
            f"/api/admin/reports/{report_id}/attachments",
            data={"attachment_type": "AFTER"},
            files=[("images", ("after-3.png", PNG_BYTES, "image/png"))],
            headers=self.auth_headers("receiver", "receiver-password"),
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(receiver_response.status_code, 403)
        attachments = response.json()["attachments"]
        after_images = [item for item in attachments if item["attachment_type"] == "AFTER"]
        self.assertEqual(len(after_images), 2)
        self.assertTrue(all(item["is_public"] for item in after_images))
        with self.SessionTesting() as db:
            stored = db.query(Attachment).filter(Attachment.report_id == report_id).all()
            self.assertEqual(len([item for item in stored if item.attachment_type.value == "AFTER"]), 2)

    def test_assignment_workflow_enforces_rbac_filters_history_and_audit(self):
        report_id = self.report_id("YT360-AAAAAA")
        handler = self.user_id("handler")

        forbidden = self.client.post(
            f"/api/admin/reports/{report_id}/assignment",
            json={
                "assigned_to": handler,
                "assigned_department": "To xu ly nhanh",
                "priority": "HIGH",
                "reason": "Handler khong duoc phan cong.",
                "expected_assignment_version": 0,
            },
            headers=self.auth_headers("handler", "handler-password"),
        )
        response = self.client.post(
            f"/api/admin/reports/{report_id}/assignment",
            json={
                "assigned_to": handler,
                "assigned_department": "To xu ly nhanh",
                "priority": "URGENT",
                "reason": "Can xu ly gap theo V2.5.",
                "expected_assignment_version": 0,
            },
            headers=self.auth_headers("receiver", "receiver-password"),
        )

        self.assertEqual(forbidden.status_code, 403)
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["assigned_to"]["username"], "handler")
        self.assertEqual(body["assigned_department"], "To xu ly nhanh")
        self.assertEqual(body["priority"], ReportPriority.URGENT.value)
        self.assertEqual(body["assignment_version"], 1)
        self.assertEqual(len(body["assignment_history"]), 1)
        self.assertEqual(body["assignment_history"][0]["changed_by"]["username"], "receiver")
        self.assertEqual(body["assignment_history"][0]["new_assigned_to"]["username"], "handler")
        self.assertEqual(body["assignment_history"][0]["reason"], "Can xu ly gap theo V2.5.")

        my_work = self.client.get("/api/admin/reports/my-work", headers=self.auth_headers("handler", "handler-password"))
        filtered = self.client.get(
            "/api/admin/reports",
            params={"assigned_to": handler, "assigned_department": "xu ly", "priority": "URGENT"},
            headers=self.auth_headers(),
        )

        self.assertEqual(my_work.status_code, 200)
        self.assertIn(report_id, [item["id"] for item in my_work.json()["items"]])
        self.assertEqual(filtered.status_code, 200)
        self.assertEqual(filtered.json()["total"], 1)
        self.assertEqual(filtered.json()["items"][0]["assigned_to"]["username"], "handler")
        with self.SessionTesting() as db:
            history = db.query(ReportAssignmentHistory).filter(ReportAssignmentHistory.report_id == report_id).one()
            self.assertEqual(history.changed_by_user.username, "receiver")
            self.assertEqual(history.new_assigned_to_user.username, "handler")
            audit = db.query(AuditLog).filter(AuditLog.action == "REPORT_ASSIGNMENT_CHANGE").one()
            self.assertEqual(audit.user.username, "receiver")

    def test_assignment_rejects_stale_assignment_version(self):
        report_id = self.report_id("YT360-AAAAAA")
        handler = self.user_id("handler")

        first = self.client.post(
            f"/api/admin/reports/{report_id}/assignment",
            json={
                "assigned_to": handler,
                "assigned_department": "To xu ly nhanh",
                "priority": "HIGH",
                "reason": "Phan cong lan dau.",
                "expected_assignment_version": 0,
            },
            headers=self.auth_headers("receiver", "receiver-password"),
        )
        stale = self.client.post(
            f"/api/admin/reports/{report_id}/assignment",
            json={
                "assigned_to": handler,
                "assigned_department": "To khac",
                "priority": "URGENT",
                "reason": "Du lieu cu khong duoc ghi de.",
                "expected_assignment_version": 0,
            },
            headers=self.auth_headers("admin", "admin-password"),
        )
        current = self.client.get(
            f"/api/admin/reports/{report_id}",
            headers=self.auth_headers("admin", "admin-password"),
        )

        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json()["assignment_version"], 1)
        self.assertEqual(stale.status_code, 409)
        self.assertEqual(current.status_code, 200)
        self.assertEqual(current.json()["assigned_department"], "To xu ly nhanh")
        self.assertEqual(current.json()["priority"], ReportPriority.HIGH.value)
        self.assertEqual(current.json()["assignment_version"], 1)
        self.assertEqual(len(current.json()["assignment_history"]), 1)

    def test_v27_internal_notes_secure_additional_info_and_audit(self):
        report_id = self.report_id("YT360-AAAAAA")
        admin_headers = self.auth_headers("admin", "admin-password")

        note_response = self.client.post(
            f"/api/admin/reports/{report_id}/internal-notes",
            json={"note": "SECRET V27 INTERNAL NOTE"},
            headers=admin_headers,
        )
        request_response = self.client.post(
            f"/api/admin/reports/{report_id}/additional-info-requests",
            json={
                "public_message": "Vui long bo sung mo ta hien truong.",
                "internal_note": "SECRET REQUEST INTERNAL NOTE",
            },
            headers=admin_headers,
        )

        self.assertEqual(note_response.status_code, 201)
        self.assertEqual(note_response.json()["internal_notes"][0]["note"], "SECRET V27 INTERNAL NOTE")
        self.assertEqual(request_response.status_code, 201)
        request_body = request_response.json()
        self.assertTrue(request_body["submission_token"])
        self.assertIn("/bo-sung?token=", request_body["submission_url"])

        expiring_response = self.client.post(
            f"/api/admin/reports/{report_id}/additional-info-requests",
            json={"public_message": "Yeu cau se het han trong test."},
            headers=admin_headers,
        )
        self.assertEqual(expiring_response.status_code, 201)
        with self.SessionTesting() as db:
            expiring_item = db.query(AdditionalInfoRequest).filter(
                AdditionalInfoRequest.id == expiring_response.json()["id"]
            ).one()
            expiring_item.response_token_expires_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=1)
            db.commit()
        expired_token = self.client.post(
            f"/api/public/additional-info/{expiring_response.json()['submission_token']}",
            json={"response_text": "Expired token must fail."},
        )

        wrong_token = self.client.post(
            "/api/public/additional-info/not-a-valid-secret-token-value-123456789",
            json={"response_text": "Attempt with wrong token."},
        )
        valid_token = self.client.post(
            f"/api/public/additional-info/{request_body['submission_token']}",
            json={"response_text": "Thong tin bo sung tu nguoi dan."},
        )
        replay = self.client.post(
            f"/api/public/additional-info/{request_body['submission_token']}",
            json={"response_text": "Replay must fail."},
        )
        public_lookup = self.client.get("/api/public/reports/YT360-AAAAAA")

        self.assertEqual(wrong_token.status_code, 404)
        self.assertEqual(expired_token.status_code, 410)
        self.assertEqual(valid_token.status_code, 200)
        self.assertIn(replay.status_code, {404, 409})
        self.assertEqual(public_lookup.status_code, 200)
        public_text = public_lookup.text.lower()
        self.assertNotIn("secret v27 internal note", public_text)
        self.assertNotIn("secret request internal note", public_text)
        self.assertNotIn("submission_token", public_text)
        self.assertNotIn("response_text", public_text)
        self.assertEqual(public_lookup.json()["additional_info_requests"][0]["status"], "RESPONDED")

        detail = self.client.get(f"/api/admin/reports/{report_id}", headers=admin_headers)
        self.assertEqual(detail.status_code, 200)
        self.assertTrue(any(item["event_type"] == "INTERNAL_NOTE" for item in detail.json()["timeline"]))
        self.assertTrue(any(item["event_type"] == "PUBLIC_RESPONSE" for item in detail.json()["timeline"]))
        with self.SessionTesting() as db:
            request_item = db.query(AdditionalInfoRequest).filter(
                AdditionalInfoRequest.id == request_body["id"]
            ).one()
            self.assertEqual(request_item.status, AdditionalInfoRequestStatus.RESPONDED)
            self.assertIsNone(request_item.response_token_hash)
            self.assertEqual(request_item.response_text, "Thong tin bo sung tu nguoi dan.")
            self.assertEqual(db.query(ReportInternalNote).filter(ReportInternalNote.report_id == report_id).count(), 1)
            actions = {item.action for item in db.query(AuditLog).all()}
            self.assertIn("REPORT_INTERNAL_NOTE_ADD", actions)
            self.assertIn("REPORT_ADDITIONAL_INFO_REQUEST", actions)
            self.assertIn("PUBLIC_ADDITIONAL_INFO_RESPONSE", actions)

    def test_v27_out_of_scope_requires_public_reason_and_keeps_report(self):
        report_id = self.report_id("YT360-AAAAAA")
        headers = self.auth_headers("receiver", "receiver-password")

        missing_reason = self.client.post(
            f"/api/admin/reports/{report_id}/out-of-scope",
            json={"internal_note": "No public reason."},
            headers=headers,
        )
        valid = self.client.post(
            f"/api/admin/reports/{report_id}/out-of-scope",
            json={"public_note": "Khong thuoc tham quyen. Vui long lien he don vi chuyen mon."},
            headers=headers,
        )

        self.assertEqual(missing_reason.status_code, 422)
        self.assertEqual(valid.status_code, 200)
        self.assertEqual(valid.json()["status"], "OUT_OF_SCOPE")
        with self.SessionTesting() as db:
            self.assertIsNotNone(db.get(Report, report_id))

    def test_v27_additional_info_token_accepts_only_one_concurrent_response(self):
        report_id = self.report_id("YT360-AAAAAA")
        created = self.client.post(
            f"/api/admin/reports/{report_id}/additional-info-requests",
            json={"public_message": "Vui long bo sung thong tin dong thoi."},
            headers=self.auth_headers("admin", "admin-password"),
        )
        self.assertEqual(created.status_code, 201)
        token = created.json()["submission_token"]

        def submit(value: str):
            with TestClient(self.app) as client:
                return client.post(
                    f"/api/public/additional-info/{token}",
                    json={"response_text": value},
                )

        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(pool.map(submit, ["Phan hoi A", "Phan hoi B"]))

        status_codes = [response.status_code for response in responses]
        self.assertEqual(status_codes.count(200), 1)
        self.assertIn(next(code for code in status_codes if code != 200), {404, 409})
        with self.SessionTesting() as db:
            request_item = db.query(AdditionalInfoRequest).filter(
                AdditionalInfoRequest.id == created.json()["id"]
            ).one()
            self.assertIn(request_item.response_text, {"Phan hoi A", "Phan hoi B"})
            self.assertEqual(request_item.status, AdditionalInfoRequestStatus.RESPONDED)
            self.assertIsNone(request_item.response_token_hash)
            audit_count = db.query(AuditLog).filter(
                AuditLog.action == "PUBLIC_ADDITIONAL_INFO_RESPONSE",
                AuditLog.entity_id == request_item.id,
            ).count()
            self.assertEqual(audit_count, 1)

    def test_processing_image_upload_rejects_initial_type(self):
        report_id = self.assign_report_to_user("YT360-AAAAAA")

        response = self.client.post(
            f"/api/admin/reports/{report_id}/attachments",
            data={"attachment_type": "INITIAL"},
            files=[("images", ("fake-initial.png", PNG_BYTES, "image/png"))],
            headers=self.auth_headers("handler", "handler-password"),
        )

        self.assertEqual(response.status_code, 422)

    def test_processing_image_upload_rejects_empty_file_list(self):
        report_id = self.assign_report_to_user("YT360-AAAAAA")

        response = self.client.post(
            f"/api/admin/reports/{report_id}/attachments",
            data={"attachment_type": "AFTER"},
            headers=self.auth_headers("handler", "handler-password"),
        )

        self.assertIn(response.status_code, {400, 422})

    def test_admin_only_report_technical_metadata_endpoint(self):
        report_id = self.report_id("YT360-AAAAAA")
        with self.SessionTesting() as db:
            report = db.get(Report, report_id)
            report.reporter_ip_hash = "ip-hash"
            report.reporter_user_agent_hash = "ua-hash"
            report.request_fingerprint_hash = "fingerprint-hash"
            report.client_submitted_at = datetime(2026, 10, 7, 9, 30, 0)
            report.technical_metadata = json.dumps(
                {
                    "client_ip_source": "direct",
                    "client_ip": "192.0.2.1",
                    "user_agent": "Admin visible UA",
                    "observed_source_port": 45678,
                    "source_port_note": "Transport metadata only; not a device or person identifier.",
                }
            )
            db.commit()

        admin_response = self.client.get(
            f"/api/admin/reports/{report_id}/technical",
            headers=self.auth_headers(),
        )
        receiver_response = self.client.get(
            f"/api/admin/reports/{report_id}/technical",
            headers=self.auth_headers("receiver", "receiver-password"),
        )
        no_auth_response = self.client.get(f"/api/admin/reports/{report_id}/technical")

        self.assertEqual(admin_response.status_code, 200)
        body = admin_response.json()
        self.assertEqual(body["tracking_code"], "YT360-AAAAAA")
        self.assertEqual(body["reporter_ip_hash"], "ip-hash")
        self.assertEqual(body["reporter_user_agent_hash"], "ua-hash")
        self.assertEqual(body["request_fingerprint_hash"], "fingerprint-hash")
        self.assertEqual(body["technical_metadata"]["client_ip"], "192.0.2.1")
        self.assertEqual(body["technical_metadata"]["user_agent"], "Admin visible UA")
        self.assertEqual(body["technical_metadata"]["observed_source_port"], 45678)
        self.assertEqual(receiver_response.status_code, 403)
        self.assertEqual(no_auth_response.status_code, 401)

    def test_admin_can_block_and_unblock_report_source(self):
        report_id = self.report_id("YT360-AAAAAA")
        with self.SessionTesting() as db:
            report = db.get(Report, report_id)
            report.reporter_ip_hash = "ip-hash-for-block"
            report.request_fingerprint_hash = "fingerprint-hash-for-block"
            db.commit()

        headers = self.auth_headers()
        block_response = self.client.post(
            f"/api/admin/reports/{report_id}/source-blocks",
            json={"source_type": "FINGERPRINT", "reason": "Repeated abuse"},
            headers=headers,
        )
        receiver_response = self.client.post(
            f"/api/admin/reports/{report_id}/source-blocks",
            json={"source_type": "FINGERPRINT"},
            headers=self.auth_headers("receiver", "receiver-password"),
        )

        self.assertEqual(block_response.status_code, 201)
        body = block_response.json()
        self.assertEqual(body["source_type"], "FINGERPRINT")
        self.assertEqual(body["source_hash"], "fingerprint-hash-for-block")
        self.assertTrue(body["is_active"])
        self.assertEqual(receiver_response.status_code, 403)

        technical_response = self.client.get(f"/api/admin/reports/{report_id}/technical", headers=headers)
        self.assertEqual(technical_response.status_code, 200)
        self.assertEqual(len(technical_response.json()["active_source_blocks"]), 1)

        unblock_response = self.client.post(f"/api/admin/source-blocks/{body['id']}/unblock", headers=headers)
        self.assertEqual(unblock_response.status_code, 200)
        self.assertFalse(unblock_response.json()["is_active"])
        with self.SessionTesting() as db:
            source_block = db.get(ReportSourceBlock, body["id"])
            self.assertFalse(source_block.is_active)
            self.assertIsNotNone(source_block.lifted_at)

    def test_valid_receive_transition_updates_report_history_and_audit_log(self):
        report_id = self.report_id("YT360-AAAAAA")

        response = self.client.post(
            f"/api/admin/reports/{report_id}/receive",
            json={"internal_note": "Checked initial information."},
            headers=self.auth_headers("receiver", "receiver-password"),
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "RECEIVED")
        with self.SessionTesting() as db:
            report = db.get(Report, report_id)
            self.assertEqual(report.status, ReportStatus.RECEIVED)
            history = db.query(StatusHistory).filter(StatusHistory.report_id == report_id).one()
            self.assertEqual(history.old_status, ReportStatus.NEW)
            self.assertEqual(history.new_status, ReportStatus.RECEIVED)
            self.assertEqual(history.changed_by_user.username, "receiver")
            audit = db.query(AuditLog).filter(AuditLog.entity_id == report_id).one()
            self.assertEqual(audit.action, "REPORT_RECEIVE")
            self.assertEqual(audit.user.username, "receiver")

    def test_invalid_direct_new_to_resolved_transition_is_rejected(self):
        report_id = self.report_id("YT360-AAAAAA")

        response = self.client.post(
            f"/api/admin/reports/{report_id}/resolve",
            json={"public_note": "Resolved directly."},
            headers=self.auth_headers("admin", "admin-password"),
        )

        self.assertEqual(response.status_code, 409)
        with self.SessionTesting() as db:
            report = db.get(Report, report_id)
            self.assertEqual(report.status, ReportStatus.NEW)
            self.assertEqual(db.query(StatusHistory).filter(StatusHistory.report_id == report_id).count(), 0)
            self.assertEqual(db.query(AuditLog).filter(AuditLog.entity_id == report_id).count(), 0)

    def test_authorization_blocks_handler_from_receiving_report(self):
        report_id = self.report_id("YT360-AAAAAA")

        response = self.client.post(
            f"/api/admin/reports/{report_id}/receive",
            json={},
            headers=self.auth_headers("handler", "handler-password"),
        )

        self.assertEqual(response.status_code, 403)

    def test_coordinate_transition_stores_public_and_internal_notes(self):
        report_id = self.report_id("YT360-DDDDDD")

        response = self.client.post(
            f"/api/admin/reports/{report_id}/coordinate",
            json={
                "internal_note": "Coordinate this case.",
                "public_note": "Dang phoi hop xu ly.",
                "coordination_target": "To ha tang",
            },
            headers=self.auth_headers("receiver", "receiver-password"),
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], "COORDINATING")
        self.assertIn("To ha tang", body["internal_note"])
        self.assertEqual(body["status_history"][0]["public_note"], "Dang phoi hop xu ly.")

    def test_resolve_transition_requires_public_result(self):
        report_id = self.assign_report_to_user("YT360-BBBBBB")

        response = self.client.post(
            f"/api/admin/reports/{report_id}/resolve",
            json={"internal_note": "Missing public result."},
            headers=self.auth_headers("handler", "handler-password"),
        )

        self.assertEqual(response.status_code, 422)

    def test_handler_can_resolve_coordinating_report_with_public_result(self):
        report_id = self.assign_report_to_user("YT360-BBBBBB")

        response = self.client.post(
            f"/api/admin/reports/{report_id}/resolve",
            json={"public_note": "Da thong nhat bien phap xu ly."},
            headers=self.auth_headers("handler", "handler-password"),
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], "RESOLVED")
        self.assertEqual(body["public_response"], "Da thong nhat bien phap xu ly.")
        with self.SessionTesting() as db:
            report = db.get(Report, report_id)
            self.assertEqual(report.status, ReportStatus.RESOLVED)
            self.assertEqual(report.public_response, "Da thong nhat bien phap xu ly.")
            audit = db.query(AuditLog).filter(AuditLog.entity_id == report_id).one()
            self.assertEqual(audit.action, "REPORT_RESOLVE")
            self.assertEqual(audit.user.username, "handler")

    def test_out_of_scope_transition_is_allowed_for_receiver(self):
        report_id = self.report_id("YT360-AAAAAA")

        response = self.client.post(
            f"/api/admin/reports/{report_id}/out-of-scope",
            json={"public_note": "Noi dung khong thuoc pham vi tiep nhan."},
            headers=self.auth_headers("receiver", "receiver-password"),
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "OUT_OF_SCOPE")

    def test_transition_rolls_back_when_audit_log_fails(self):
        report_id = self.report_id("YT360-AAAAAA")

        with patch("app.api.v1.admin.add_audit_log", side_effect=RuntimeError("audit failed")):
            with self.assertRaises(RuntimeError):
                self.client.post(
                    f"/api/admin/reports/{report_id}/receive",
                    json={"internal_note": "This operation must rollback."},
                    headers=self.auth_headers("admin", "admin-password"),
                )

        with self.SessionTesting() as db:
            report = db.get(Report, report_id)
            self.assertEqual(report.status, ReportStatus.NEW)
            self.assertIsNone(report.internal_note)
            self.assertEqual(db.query(StatusHistory).filter(StatusHistory.report_id == report_id).count(), 0)
            self.assertEqual(db.query(AuditLog).filter(AuditLog.entity_id == report_id).count(), 0)

    def test_update_requires_authentication_and_rejects_invalid_token(self):
        report_id = self.report_id("YT360-AAAAAA")

        no_auth = self.client.post(f"/api/admin/reports/{report_id}/receive", json={})
        bad_token = self.client.post(
            f"/api/admin/reports/{report_id}/receive",
            json={},
            headers={"Authorization": "Bearer invalid-token"},
        )

        self.assertEqual(no_auth.status_code, 401)
        self.assertEqual(bad_token.status_code, 401)
        with self.SessionTesting() as db:
            report = db.get(Report, report_id)
            self.assertEqual(report.status, ReportStatus.NEW)
            self.assertEqual(db.query(StatusHistory).filter(StatusHistory.report_id == report_id).count(), 0)

    def test_transition_rejects_missing_report_and_invalid_payload(self):
        headers = self.auth_headers("admin", "admin-password")
        missing = self.client.post("/api/admin/reports/999999/receive", json={}, headers=headers)
        bad_id = self.client.get("/api/admin/reports/not-an-id", headers=headers)
        too_long = self.client.post(
            f"/api/admin/reports/{self.report_id('YT360-AAAAAA')}/receive",
            json={"internal_note": "x" * 2001},
            headers=headers,
        )
        wrong_body = self.client.post(
            f"/api/admin/reports/{self.report_id('YT360-AAAAAA')}/receive",
            json={"internal_note": {"not": "a string"}},
            headers=headers,
        )

        self.assertEqual(missing.status_code, 404)
        self.assertEqual(bad_id.status_code, 422)
        self.assertEqual(too_long.status_code, 422)
        self.assertEqual(wrong_body.status_code, 422)

    def test_public_lookup_shows_public_response_and_never_leaks_internal_data(self):
        report_id = self.assign_report_to_user("YT360-DDDDDD")
        receiver_headers = self.auth_headers("receiver", "receiver-password")
        handler_headers = self.auth_headers("handler", "handler-password")

        self.assertEqual(
            self.client.post(
                f"/api/admin/reports/{report_id}/coordinate",
                json={
                    "coordination_target": "To test phoi hop",
                    "internal_note": "INTERNAL TEST NOTE MUST NOT LEAK",
                    "public_note": "Dang phoi hop TEST.",
                },
                headers=receiver_headers,
            ).status_code,
            200,
        )
        response = self.client.post(
            f"/api/admin/reports/{report_id}/resolve",
            json={
                "internal_note": "SECOND INTERNAL TEST NOTE MUST NOT LEAK",
                "public_note": "Da kiem tra phan anh thu nghiem. Day la du lieu TEST.",
            },
            headers=handler_headers,
        )

        self.assertEqual(response.status_code, 200)
        public_response = self.client.get("/api/public/reports/YT360-DDDDDD")
        self.assertEqual(public_response.status_code, 200)
        body = public_response.json()
        self.assertEqual(body["public_status"]["code"], "RESOLVED")
        self.assertEqual(body["public_response"], "Da kiem tra phan anh thu nghiem. Day la du lieu TEST.")
        self.assertEqual(
            [item["public_status"]["code"] for item in body["public_status_history"]],
            ["COORDINATING", "RESOLVED"],
        )
        lower_text = public_response.text.lower()
        self.assertNotIn("internal", lower_text)
        self.assertNotIn("audit", lower_text)
        self.assertNotIn("username", lower_text)
        self.assertNotIn("password", lower_text)
        self.assertNotIn("token", lower_text)

    def test_dashboard_statistics_update_after_status_change(self):
        headers = self.auth_headers("handler", "handler-password")
        report_id = self.assign_report_to_user("YT360-BBBBBB")
        before = self.client.get("/api/admin/dashboard", headers=self.auth_headers()).json()
        before_cards = {card["key"]: card["value"] for card in before["cards"]}

        response = self.client.post(
            f"/api/admin/reports/{report_id}/resolve",
            json={"public_note": "Resolved for dashboard count."},
            headers=headers,
        )
        after = self.client.get("/api/admin/dashboard", headers=self.auth_headers()).json()
        after_cards = {card["key"]: card["value"] for card in after["cards"]}

        self.assertEqual(response.status_code, 200)
        self.assertEqual(after_cards["coordinating"], before_cards["coordinating"] - 1)
        self.assertEqual(after_cards["resolved"], before_cards["resolved"] + 1)

    def test_admin_statistics_counts_groups_filters_and_empty_state(self):
        headers = self.auth_headers()
        with self.SessionTesting() as db:
            inactive_category = Category(
                name="=TEST Category",
                icon="formula",
                is_active=False,
                display_order=99,
            )
            inactive_area = Area(name="+TEST Area", is_active=False, display_order=99)
            db.add_all([inactive_category, inactive_area])
            db.flush()
            report = Report(
                tracking_code="YT360-EEE111",
                category_id=inactive_category.id,
                area_id=inactive_area.id,
                description="Formula safety source.",
                status=ReportStatus.OUT_OF_SCOPE,
                internal_note="INTERNAL NOTE MUST NOT EXPORT",
                public_response="Public only.",
            )
            db.add(report)
            db.flush()
            report.created_at = datetime(2026, 9, 30, 16, 59, 59)
            report.updated_at = datetime(2026, 9, 30, 17, 5, 0)
            db.commit()

        response = self.client.get("/api/admin/statistics", headers=headers)

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["total_reports"], 5)
        self.assertEqual(body["new_reports"], 1)
        self.assertEqual(body["received_reports"], 1)
        self.assertEqual(body["coordinating_reports"], 1)
        self.assertEqual(body["resolved_reports"], 1)
        self.assertEqual(body["out_of_scope_reports"], 1)
        with self.SessionTesting() as db:
            category_1_name = db.get(Category, self.category_id).name
            category_2_name = db.get(Category, self.category_2_id).name
            area_1_name = db.get(Area, self.area_id).name
            area_2_name = db.get(Area, self.area_2_id).name
        category_counts = {item["label"]: item["value"] for item in body["by_category"]}
        area_counts = {item["label"]: item["value"] for item in body["by_area"]}
        self.assertEqual(category_counts[category_1_name], 3)
        self.assertEqual(category_counts[category_2_name], 1)
        self.assertEqual(category_counts["=TEST Category"], 1)
        self.assertEqual(area_counts[area_1_name], 3)
        self.assertEqual(area_counts[area_2_name], 1)
        self.assertEqual(area_counts["+TEST Area"], 1)

        filtered = self.client.get(
            "/api/admin/statistics",
            params={
                "status": "OUT_OF_SCOPE",
                "from_date": "2026-09-30",
                "to_date": "2026-09-30",
            },
            headers=headers,
        )
        self.assertEqual(filtered.status_code, 200)
        self.assertEqual(filtered.json()["total_reports"], 1)
        self.assertEqual(filtered.json()["out_of_scope_reports"], 1)

        empty = self.client.get(
            "/api/admin/statistics",
            params={"from_date": "1999-01-01", "to_date": "1999-01-02"},
            headers=headers,
        )
        self.assertEqual(empty.status_code, 200)
        self.assertEqual(empty.json()["total_reports"], 0)
        self.assertEqual(empty.json()["by_category"], [])
        self.assertEqual(empty.json()["by_area"], [])
        self.assertEqual(empty.json()["by_date"], [])

    def test_admin_statistics_and_export_require_valid_auth_for_all_roles(self):
        for path in ["/api/admin/statistics", "/api/admin/statistics/export"]:
            self.assertEqual(self.client.get(path).status_code, 401)
            self.assertEqual(self.client.get(path, headers={"Authorization": "Bearer bad-token"}).status_code, 401)
            self.assertEqual(self.client.get(path, headers=self.auth_headers("admin", "admin-password")).status_code, 200)
            self.assertEqual(
                self.client.get(path, headers=self.auth_headers("receiver", "receiver-password")).status_code,
                200,
            )
            self.assertEqual(
                self.client.get(path, headers=self.auth_headers("handler", "handler-password")).status_code,
                200,
            )

    def test_excel_export_is_valid_filtered_and_does_not_leak_sensitive_fields(self):
        headers = self.auth_headers()
        with self.SessionTesting() as db:
            category = db.get(Category, self.category_id)
            area = db.get(Area, self.area_id)
            report = db.query(Report).filter(Report.tracking_code == "YT360-AAAAAA").one()
            report.created_at = datetime(2026, 9, 30, 16, 59, 59)
            report.updated_at = datetime(2026, 9, 30, 16, 59, 59)
            report.internal_note = "SECRET INTERNAL NOTE MUST NOT EXPORT"
            report.reporter_ip_hash = "IP HASH MUST NOT EXPORT"
            report.reporter_user_agent_hash = "UA HASH MUST NOT EXPORT"
            report.request_fingerprint_hash = "FINGERPRINT MUST NOT EXPORT"
            report.technical_metadata = json.dumps(
                {
                    "client_ip": "203.0.113.77",
                    "observed_source_port": 54321,
                    "user_agent": "SECRET USER AGENT MUST NOT EXPORT",
                }
            )
            category.name = "@TEST Category"
            area.name = "-TEST Area"
            db.commit()

        response = self.client.get(
            "/api/admin/statistics/export",
            params={
                "status": "NEW",
                "category_id": self.category_id,
                "area_id": self.area_id,
                "from_date": "2026-09-30",
                "to_date": "2026-09-30",
            },
            headers=headers,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.headers["content-type"],
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        self.assertIn("YenTruong360_ThongKe_", response.headers["content-disposition"])
        self.assertIn(".xlsx", response.headers["content-disposition"])
        sheet_xml = self.read_xlsx_sheet_xml(response.content)
        self.assertIn("Mã phản ánh", sheet_xml)
        self.assertIn("Ngày tiếp nhận", sheet_xml)
        self.assertIn("YT360-AAAAAA", sheet_xml)
        self.assertIn("'@TEST Category", sheet_xml)
        self.assertIn("'-TEST Area", sheet_xml)
        self.assertIn("Mới", sheet_xml)
        self.assertEqual(sheet_xml.count("<row "), 2)
        self.assertNotIn("password", sheet_xml.lower())
        self.assertNotIn("password_hash", sheet_xml.lower())
        self.assertNotIn("token", sheet_xml.lower())
        self.assertNotIn("audit", sheet_xml.lower())
        self.assertNotIn("SECRET INTERNAL NOTE", sheet_xml)
        self.assertNotIn("IP HASH MUST NOT EXPORT", sheet_xml)
        self.assertNotIn("UA HASH MUST NOT EXPORT", sheet_xml)
        self.assertNotIn("FINGERPRINT MUST NOT EXPORT", sheet_xml)
        self.assertNotIn("203.0.113.77", sheet_xml)
        self.assertNotIn("54321", sheet_xml)
        self.assertNotIn("SECRET USER AGENT", sheet_xml)
        self.assertNotIn("<f>", sheet_xml)
        self.assertIn('t="inlineStr"', sheet_xml)

    def test_step10_controlled_12_report_dataset_matches_db_api_and_excel(self):
        headers = self.auth_headers()
        statuses = [
            ReportStatus.NEW,
            ReportStatus.NEW,
            ReportStatus.NEW,
            ReportStatus.RECEIVED,
            ReportStatus.RECEIVED,
            ReportStatus.COORDINATING,
            ReportStatus.COORDINATING,
            ReportStatus.COORDINATING,
            ReportStatus.COORDINATING,
            ReportStatus.RESOLVED,
            ReportStatus.RESOLVED,
            ReportStatus.RESOLVED,
        ]
        dates = [
            datetime(2026, 9, 1, 0, 0, 0),
            datetime(2026, 9, 1, 12, 0, 0),
            datetime(2026, 9, 5, 9, 15, 0),
            datetime(2026, 9, 10, 11, 30, 0),
            datetime(2026, 9, 15, 8, 0, 0),
            datetime(2026, 9, 20, 13, 45, 0),
            datetime(2026, 9, 25, 16, 0, 0),
            datetime(2026, 9, 30, 0, 0, 0),
            datetime(2026, 9, 30, 16, 59, 59),
            datetime(2026, 9, 12, 10, 10, 0),
            datetime(2026, 9, 18, 10, 10, 0),
            datetime(2026, 9, 28, 10, 10, 0),
        ]
        with self.SessionTesting() as db:
            for existing_report in db.query(Report).all():
                existing_report.created_at = datetime(2025, 1, 1, 0, 0, 0)
                existing_report.updated_at = datetime(2025, 1, 1, 0, 0, 0)
            categories = [
                Category(name="Step10 Category A", icon="a", display_order=10, is_active=True),
                Category(name="Step10 Category B", icon="b", display_order=11, is_active=True),
                Category(name="Step10 Category C inactive", icon="c", display_order=12, is_active=False),
            ]
            areas = [
                Area(name="Step10 Area A", display_order=10, is_active=True),
                Area(name="Step10 Area B", display_order=11, is_active=True),
                Area(name="Step10 Area C inactive", display_order=12, is_active=False),
            ]
            db.add_all(categories + areas)
            db.flush()
            for index, status_value in enumerate(statuses):
                report = Report(
                    tracking_code=f"YT360-S10{index:03d}",
                    category_id=categories[index % 3].id,
                    area_id=areas[index % 3].id,
                    description=f"Step 10 controlled report {index}",
                    status=status_value,
                )
                db.add(report)
                db.flush()
                report.created_at = dates[index]
                report.updated_at = dates[index]
            db.commit()
            expected_total = (
                db.query(Report)
                .filter(Report.tracking_code.like("YT360-S10%"))
                .count()
            )

        response = self.client.get(
            "/api/admin/statistics",
            params={"from_date": "2026-09-01", "to_date": "2026-09-30"},
            headers=headers,
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(expected_total, 12)
        self.assertEqual(body["total_reports"], 12)
        self.assertEqual(body["new_reports"], 3)
        self.assertEqual(body["received_reports"], 2)
        self.assertEqual(body["coordinating_reports"], 4)
        self.assertEqual(body["resolved_reports"], 3)
        self.assertEqual(body["out_of_scope_reports"], 0)
        self.assertEqual({item["label"]: item["value"] for item in body["by_category"]}, {
            "Step10 Category A": 4,
            "Step10 Category B": 4,
            "Step10 Category C inactive": 4,
        })
        self.assertEqual({item["label"]: item["value"] for item in body["by_area"]}, {
            "Step10 Area A": 4,
            "Step10 Area B": 4,
            "Step10 Area C inactive": 4,
        })

        excel = self.client.get(
            "/api/admin/statistics/export",
            params={"from_date": "2026-09-01", "to_date": "2026-09-30"},
            headers=headers,
        )
        self.assertEqual(excel.status_code, 200)
        sheet_xml = self.read_xlsx_sheet_xml(excel.content)
        self.assertEqual(sheet_xml.count("<row "), 13)
        for code in ["YT360-S10000", "YT360-S10007", "YT360-S10008", "YT360-S10011"]:
            self.assertIn(code, sheet_xml)

    def read_xlsx_sheet_xml(self, content: bytes) -> str:
        with ZipFile(BytesIO(content)) as workbook:
            self.assertIn("xl/workbook.xml", workbook.namelist())
            self.assertIn("xl/worksheets/sheet1.xml", workbook.namelist())
            return workbook.read("xl/worksheets/sheet1.xml").decode("utf-8")

    def test_duplicate_receive_does_not_create_duplicate_history(self):
        report_id = self.report_id("YT360-AAAAAA")
        headers = self.auth_headers("receiver", "receiver-password")

        first = self.client.post(f"/api/admin/reports/{report_id}/receive", json={}, headers=headers)
        second = self.client.post(f"/api/admin/reports/{report_id}/receive", json={}, headers=headers)

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 409)
        with self.SessionTesting() as db:
            self.assertEqual(db.query(StatusHistory).filter(StatusHistory.report_id == report_id).count(), 1)
            self.assertEqual(db.query(AuditLog).filter(AuditLog.entity_id == report_id).count(), 1)

    def test_attachment_endpoint_rejects_directory_traversal_filename(self):
        outside_file = Path(self.temp_dir.name) / "outside.png"
        outside_file.write_bytes(b"not a real image")
        report_id = self.report_id("YT360-AAAAAA")
        with self.SessionTesting() as db:
            attachment = Attachment(
                report_id=report_id,
                stored_filename="../outside.png",
                original_filename="outside.png",
                mime_type="image/png",
                file_size=outside_file.stat().st_size,
            )
            db.add(attachment)
            db.commit()
            attachment_id = attachment.id

        response = self.client.get(
            f"/api/admin/reports/{report_id}/attachments/{attachment_id}",
            headers=self.auth_headers(),
        )

        self.assertEqual(response.status_code, 404)

    def test_attachment_endpoint_serves_database_fallback_when_file_is_missing(self):
        report_id = self.report_id("YT360-AAAAAA")
        with self.SessionTesting() as db:
            attachment = Attachment(
                report_id=report_id,
                stored_filename="missing-but-backed-up.png",
                original_filename="backup.png",
                mime_type="image/png",
                file_size=len(PNG_BYTES),
                file_data=PNG_BYTES,
            )
            db.add(attachment)
            db.commit()
            attachment_id = attachment.id

        response = self.client.get(
            f"/api/admin/reports/{report_id}/attachments/{attachment_id}",
            headers=self.auth_headers(),
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "image/png")
        self.assertEqual(response.content, PNG_BYTES)

    def test_admin_role_can_access_admin_endpoint(self):
        response = self.client.get("/api/admin/system", headers=self.auth_headers("admin", "admin-password"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["permission"], "admin")

    def test_wrong_role_is_forbidden(self):
        response = self.client.get("/api/admin/receive-work", headers=self.auth_headers("handler", "handler-password"))

        self.assertEqual(response.status_code, 403)

    def test_receiver_role_can_access_receiver_endpoint(self):
        response = self.client.get("/api/admin/receive-work", headers=self.auth_headers("receiver", "receiver-password"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["permission"], "receive")

    def test_handler_role_can_access_handler_endpoint(self):
        response = self.client.get("/api/admin/handle-work", headers=self.auth_headers("handler", "handler-password"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["permission"], "handle")


if __name__ == "__main__":
    unittest.main()
