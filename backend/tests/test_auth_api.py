import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

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
        settings.auth_secret_key = "unit-test-secret-key-change-me"
        settings.auth_token_expire_seconds = 900
        settings.upload_dir = str(Path(self.temp_dir.name) / "uploads")
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
