import tempfile
import unittest
from datetime import datetime
from io import BytesIO
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core import security
from app.core.config import settings
from app.core.security import hash_password
from app.db.base import Base
from app.db.dependencies import get_db
from app.main import create_app
from app.models import Area, Attachment, AuditLog, Category, Report, ReportStatus, StatusHistory, User


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
        self.assertEqual(body["status_history"], [])

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
        report_id = self.report_id("YT360-BBBBBB")

        response = self.client.post(
            f"/api/admin/reports/{report_id}/resolve",
            json={"internal_note": "Missing public result."},
            headers=self.auth_headers("handler", "handler-password"),
        )

        self.assertEqual(response.status_code, 422)

    def test_handler_can_resolve_coordinating_report_with_public_result(self):
        report_id = self.report_id("YT360-BBBBBB")

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
        report_id = self.report_id("YT360-DDDDDD")
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
        before = self.client.get("/api/admin/dashboard", headers=self.auth_headers()).json()
        before_cards = {card["key"]: card["value"] for card in before["cards"]}

        response = self.client.post(
            f"/api/admin/reports/{self.report_id('YT360-BBBBBB')}/resolve",
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
        self.assertIn("@TEST Category", sheet_xml)
        self.assertIn("-TEST Area", sheet_xml)
        self.assertIn("Mới", sheet_xml)
        self.assertEqual(sheet_xml.count("<row "), 2)
        self.assertNotIn("password", sheet_xml.lower())
        self.assertNotIn("password_hash", sheet_xml.lower())
        self.assertNotIn("token", sheet_xml.lower())
        self.assertNotIn("audit", sheet_xml.lower())
        self.assertNotIn("SECRET INTERNAL NOTE", sheet_xml)
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
