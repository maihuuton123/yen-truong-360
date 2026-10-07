from io import BytesIO
import json
from pathlib import Path
import tempfile
import unittest
from zipfile import ZipFile

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.api.v1 import public as public_api
from app.core import security
from app.core.config import settings
from app.core.rate_limit import public_lookup_limiter, public_report_limiter
from app.core.security import hash_password
from app.db.base import Base
from app.db.dependencies import get_db
from app.main import create_app
from app.models import Area, AuditLog, Category, Report, ReportStatus, StatusHistory, User


PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


class V1EndToEndTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        database_path = Path(self.temp_dir.name) / "test.db"
        self.engine = create_engine(f"sqlite:///{database_path}", connect_args={"check_same_thread": False})
        self.SessionTesting = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        Base.metadata.create_all(bind=self.engine)

        self.previous_upload_dir = settings.upload_dir
        self.previous_secret = settings.auth_secret_key
        self.previous_expiration = settings.auth_token_expire_seconds
        self.previous_report_rate_limit = settings.public_report_rate_limit
        self.previous_lookup_rate_limit = settings.public_lookup_rate_limit
        settings.upload_dir = str(Path(self.temp_dir.name) / "uploads")
        settings.auth_secret_key = "step-12-e2e-secret"
        settings.auth_token_expire_seconds = 1800
        settings.public_report_rate_limit = 100
        settings.public_lookup_rate_limit = 100
        public_report_limiter.reset()
        public_lookup_limiter.reset()
        security.reset_revoked_tokens()

        self.category_id, self.area_id = self.seed_data()
        app = create_app()
        app.dependency_overrides[get_db] = self.override_get_db
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        self.engine.dispose()
        settings.upload_dir = self.previous_upload_dir
        settings.auth_secret_key = self.previous_secret
        settings.auth_token_expire_seconds = self.previous_expiration
        settings.public_report_rate_limit = self.previous_report_rate_limit
        settings.public_lookup_rate_limit = self.previous_lookup_rate_limit
        public_report_limiter.reset()
        public_lookup_limiter.reset()
        security.reset_revoked_tokens()
        self.temp_dir.cleanup()

    def override_get_db(self):
        db = self.SessionTesting()
        try:
            yield db
        finally:
            db.close()

    def seed_data(self):
        with self.SessionTesting() as db:
            category = Category(name="Giao thông - vật cản", icon="traffic", display_order=1, is_active=True)
            area = Area(name="Khu vực demo 1", display_order=1, is_active=True)
            admin = User(
                username="admin",
                password_hash=hash_password("admin-password"),
                full_name="Quản trị phát triển",
                role="ADMIN",
                is_active=True,
            )
            db.add_all([category, area, admin])
            db.commit()
            return category.id, area.id

    def auth_headers(self):
        response = self.client.post("/api/auth/login", json={"username": "admin", "password": "admin-password"})
        self.assertEqual(response.status_code, 200)
        return {"Authorization": f"Bearer {response.json()['access_token']}"}

    def test_citizen_report_to_resolved_admin_flow_statistics_and_export(self):
        self.assertEqual(self.client.get("/api/health").status_code, 200)
        self.assertEqual(self.client.get("/api/public/categories").status_code, 200)
        self.assertEqual(self.client.get("/api/public/areas").status_code, 200)

        created = self.client.post(
            "/api/public/reports",
            headers={"User-Agent": "YT360 E2E Browser"},
            data={
                "category_id": str(self.category_id),
                "area_id": str(self.area_id),
                "description": "Cây đổ chắn ngang đường, gây cản trở giao thông.",
            },
            files={"image": ("cay-do.png", PNG_BYTES, "image/png")},
        )
        self.assertEqual(created.status_code, 201)
        self.assertIn("application/json", created.headers["content-type"])
        tracking_code = created.json()["tracking_code"]

        lookup_new = self.client.get(f"/api/public/reports/{tracking_code}")
        self.assertEqual(lookup_new.status_code, 200)
        self.assertIn("application/json", lookup_new.headers["content-type"])
        self.assertEqual(lookup_new.json()["public_status"]["code"], "NEW")
        self.assertNotIn("internal", lookup_new.text.lower())
        self.assertNotIn("audit", lookup_new.text.lower())
        self.assertNotIn("client_ip", lookup_new.text)
        self.assertNotIn("source_port", lookup_new.text)
        self.assertNotIn("user_agent", lookup_new.text)

        headers = self.auth_headers()
        dashboard = self.client.get("/api/admin/dashboard", headers=headers)
        self.assertEqual(dashboard.status_code, 200)
        cards = {item["key"]: item["value"] for item in dashboard.json()["cards"]}
        self.assertEqual(cards["new"], 1)
        self.assertEqual(cards["total"], 1)

        reports = self.client.get("/api/admin/reports", params={"tracking_code": tracking_code}, headers=headers)
        self.assertEqual(reports.status_code, 200)
        self.assertEqual(reports.json()["total"], 1)
        report_id = reports.json()["items"][0]["id"]

        detail = self.client.get(f"/api/admin/reports/{report_id}", headers=headers)
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.json()["tracking_code"], tracking_code)
        self.assertEqual(detail.json()["status"], "NEW")
        self.assertNotIn("technical_metadata", detail.json())

        technical = self.client.get(f"/api/admin/reports/{report_id}/technical", headers=headers)
        self.assertEqual(technical.status_code, 200)
        self.assertIn("application/json", technical.headers["content-type"])
        technical_body = technical.json()
        self.assertEqual(technical_body["tracking_code"], tracking_code)
        self.assertEqual(technical_body["technical_metadata"]["user_agent"], "YT360 E2E Browser")
        self.assertIn("observed_source_port", technical_body["technical_metadata"])
        self.assertIsNotNone(technical_body["client_submitted_at"])

        received = self.client.post(
            f"/api/admin/reports/{report_id}/receive",
            json={"internal_note": "Đã kiểm tra thông tin ban đầu.", "public_note": "Đã tiếp nhận phản ánh."},
            headers=headers,
        )
        self.assertEqual(received.status_code, 200)
        self.assertEqual(received.json()["status"], "RECEIVED")

        coordinated = self.client.post(
            f"/api/admin/reports/{report_id}/coordinate",
            json={
                "coordination_target": "Bộ phận giao thông",
                "internal_note": "Chuyển bộ phận phụ trách kiểm tra hiện trường.",
                "public_note": "Đang phối hợp kiểm tra và xử lý.",
            },
            headers=headers,
        )
        self.assertEqual(coordinated.status_code, 200)
        self.assertEqual(coordinated.json()["status"], "COORDINATING")

        lookup_coordinating = self.client.get(f"/api/public/reports/{tracking_code}")
        self.assertEqual(lookup_coordinating.status_code, 200)
        self.assertEqual(lookup_coordinating.json()["public_status"]["code"], "COORDINATING")
        self.assertIn("Đang phối hợp", lookup_coordinating.text)
        self.assertNotIn("Chuyển bộ phận", lookup_coordinating.text)

        resolved = self.client.post(
            f"/api/admin/reports/{report_id}/resolve",
            json={
                "internal_note": "Đã nhận xác nhận hoàn thành.",
                "public_note": "Đã dọn cây đổ, tuyến đường thông thoáng trở lại.",
            },
            headers=headers,
        )
        self.assertEqual(resolved.status_code, 200)
        self.assertEqual(resolved.json()["status"], "RESOLVED")
        self.assertEqual(resolved.json()["public_response"], "Đã dọn cây đổ, tuyến đường thông thoáng trở lại.")

        lookup_resolved = self.client.get(f"/api/public/reports/{tracking_code}")
        self.assertEqual(lookup_resolved.status_code, 200)
        lookup_body = lookup_resolved.json()
        self.assertEqual(lookup_body["public_status"]["code"], "RESOLVED")
        self.assertEqual(lookup_body["public_response"], "Đã dọn cây đổ, tuyến đường thông thoáng trở lại.")
        self.assertEqual([item["public_status"]["code"] for item in lookup_body["public_status_history"]], [
            "RECEIVED",
            "COORDINATING",
            "RESOLVED",
        ])

        with self.SessionTesting() as db:
            report = db.scalar(select(Report).where(Report.tracking_code == tracking_code))
            self.assertEqual(report.status, ReportStatus.RESOLVED)
            metadata = json.loads(report.technical_metadata)
            self.assertEqual(metadata["user_agent"], "YT360 E2E Browser")
            self.assertEqual(metadata["client_ip"], technical_body["technical_metadata"]["client_ip"])
            self.assertEqual(metadata["observed_source_port"], technical_body["technical_metadata"]["observed_source_port"])
            self.assertEqual(db.query(StatusHistory).filter(StatusHistory.report_id == report.id).count(), 3)
            self.assertEqual(db.query(AuditLog).filter(AuditLog.entity_type == "report", AuditLog.entity_id == report.id).count(), 3)

        statistics = self.client.get("/api/admin/statistics", headers=headers)
        self.assertEqual(statistics.status_code, 200)
        self.assertEqual(statistics.json()["total_reports"], 1)
        self.assertEqual(statistics.json()["resolved_reports"], 1)

        export = self.client.get("/api/admin/statistics/export", headers=headers)
        self.assertEqual(export.status_code, 200)
        self.assertEqual(
            export.headers["content-type"],
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        self.assertIn("YenTruong360_ThongKe_", export.headers["content-disposition"])
        with ZipFile(BytesIO(export.content)) as workbook:
            sheet_xml = workbook.read("xl/worksheets/sheet1.xml").decode("utf-8")
        self.assertIn(tracking_code, sheet_xml)
        self.assertIn("Giao thông - vật cản", sheet_xml)
        self.assertIn("Khu vực demo 1", sheet_xml)
        self.assertNotIn("internal_note", sheet_xml.lower())
        self.assertNotIn("audit", sheet_xml.lower())
        self.assertNotIn("password", sheet_xml.lower())


if __name__ == "__main__":
    unittest.main()
