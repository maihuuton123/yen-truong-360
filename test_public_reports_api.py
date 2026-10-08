import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.api.v1 import public as public_api
from app.core.client_metadata import USER_AGENT_MAX_LENGTH, collect_report_technical_metadata, hash_technical_value
from app.core.rate_limit import public_lookup_limiter, public_report_limiter, public_report_rapid_limiter
from app.db.base import Base
from app.db.dependencies import get_db
from app.main import create_app
from app.models import (
    Area,
    Attachment,
    AttachmentType,
    AuditLog,
    Category,
    DuplicateLinkStatus,
    Report,
    ReportDuplicateLink,
    ReportSourceBlock,
    ReportStatus,
    StatusHistory,
    User,
)


PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 24


class PublicReportsApiTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.upload_dir = Path(self.temp_dir.name) / "uploads"
        database_path = Path(self.temp_dir.name) / "test.db"
        self.engine = create_engine(f"sqlite:///{database_path}", connect_args={"check_same_thread": False})
        self.SessionTesting = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        Base.metadata.create_all(bind=self.engine)
        self.category_id, self.area_id = self.seed_base_data()

        self.previous_upload_dir = public_api.settings.upload_dir
        self.previous_max_upload_bytes = public_api.settings.max_upload_bytes
        self.previous_max_report_images = public_api.settings.max_report_images
        self.previous_duplicate_window = public_api.settings.duplicate_detection_window_hours
        self.previous_duplicate_threshold = public_api.settings.duplicate_similarity_threshold
        self.previous_duplicate_max_suggestions = public_api.settings.duplicate_max_suggestions
        self.previous_rate_limit = public_api.settings.public_report_rate_limit
        self.previous_rate_limit_window = public_api.settings.public_report_rate_limit_window_seconds
        self.previous_rapid_limit = public_api.settings.public_report_rapid_limit
        self.previous_rapid_window = public_api.settings.public_report_rapid_window_seconds
        self.previous_spam_flag_threshold = public_api.settings.public_report_spam_flag_threshold
        self.previous_lookup_rate_limit = public_api.settings.public_lookup_rate_limit
        self.previous_lookup_rate_limit_window = public_api.settings.public_lookup_rate_limit_window_seconds
        self.previous_trusted_proxy_ips = list(public_api.settings.trusted_proxy_ips)
        public_api.settings.upload_dir = str(self.upload_dir)
        public_api.settings.max_upload_bytes = 1024 * 1024
        public_api.settings.max_report_images = 5
        public_api.settings.duplicate_detection_window_hours = 72
        public_api.settings.duplicate_similarity_threshold = 0.45
        public_api.settings.duplicate_max_suggestions = 5
        public_api.settings.public_report_rate_limit = 100
        public_api.settings.public_report_rate_limit_window_seconds = 60
        public_api.settings.public_report_rapid_limit = 100
        public_api.settings.public_report_rapid_window_seconds = 10
        public_api.settings.public_report_spam_flag_threshold = 10
        public_api.settings.public_lookup_rate_limit = 100
        public_api.settings.public_lookup_rate_limit_window_seconds = 60
        public_api.settings.trusted_proxy_ips = []
        public_report_limiter.reset()
        public_report_rapid_limiter.reset()
        public_lookup_limiter.reset()

        app = create_app()
        app.dependency_overrides[get_db] = self.override_get_db
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        self.engine.dispose()
        public_api.settings.upload_dir = self.previous_upload_dir
        public_api.settings.max_upload_bytes = self.previous_max_upload_bytes
        public_api.settings.max_report_images = self.previous_max_report_images
        public_api.settings.duplicate_detection_window_hours = self.previous_duplicate_window
        public_api.settings.duplicate_similarity_threshold = self.previous_duplicate_threshold
        public_api.settings.duplicate_max_suggestions = self.previous_duplicate_max_suggestions
        public_api.settings.public_report_rate_limit = self.previous_rate_limit
        public_api.settings.public_report_rate_limit_window_seconds = self.previous_rate_limit_window
        public_api.settings.public_report_rapid_limit = self.previous_rapid_limit
        public_api.settings.public_report_rapid_window_seconds = self.previous_rapid_window
        public_api.settings.public_report_spam_flag_threshold = self.previous_spam_flag_threshold
        public_api.settings.public_lookup_rate_limit = self.previous_lookup_rate_limit
        public_api.settings.public_lookup_rate_limit_window_seconds = self.previous_lookup_rate_limit_window
        public_api.settings.trusted_proxy_ips = self.previous_trusted_proxy_ips
        public_report_limiter.reset()
        public_report_rapid_limiter.reset()
        public_lookup_limiter.reset()
        self.temp_dir.cleanup()

    def override_get_db(self):
        db = self.SessionTesting()
        try:
            yield db
        finally:
            db.close()

    def seed_base_data(self):
        with self.SessionTesting() as db:
            category = Category(name="Giao thông – vật cản", icon="traffic", display_order=1, is_active=True)
            area = Area(name="Khu vực demo 1", display_order=1, is_active=True)
            inactive_category = Category(name="Nhóm đã tắt", icon="off", display_order=2, is_active=False)
            inactive_area = Area(name="Khu vực đã tắt", display_order=2, is_active=False)
            db.add_all([category, area, inactive_category, inactive_area])
            db.commit()
            self.inactive_category_id = inactive_category.id
            self.inactive_area_id = inactive_area.id
            return category.id, area.id

    def count_reports(self):
        with self.SessionTesting() as db:
            return db.scalar(select(func.count()).select_from(Report))

    def count_attachments(self):
        with self.SessionTesting() as db:
            return db.scalar(select(func.count()).select_from(Attachment))

    def count_duplicate_links(self):
        with self.SessionTesting() as db:
            return db.scalar(select(func.count()).select_from(ReportDuplicateLink))

    def create_active_category(self, name="Nhóm khác"):
        with self.SessionTesting() as db:
            category = Category(name=name, icon="other", display_order=50, is_active=True)
            db.add(category)
            db.commit()
            return category.id

    def create_active_area(self, name="Khu vực khác"):
        with self.SessionTesting() as db:
            area = Area(name=name, display_order=50, is_active=True)
            db.add(area)
            db.commit()
            return area.id

    def test_get_categories_returns_active_seeded_data(self):
        response = self.client.get("/api/public/categories")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(len(body), 1)
        self.assertEqual(body[0]["id"], self.category_id)
        self.assertEqual(body[0]["name"], "Giao thông – vật cản")

    def test_get_areas_returns_active_seeded_data(self):
        response = self.client.get("/api/public/areas")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(len(body), 1)
        self.assertEqual(body[0]["id"], self.area_id)
        self.assertEqual(body[0]["name"], "Khu vực demo 1")

    def post_report(self, **overrides):
        data = {
            "category_id": str(self.category_id),
            "area_id": str(self.area_id),
            "description": "Cành cây chắn một phần đường đi.",
        }
        data.update(overrides.pop("data", {}))
        return self.client.post(
            "/api/public/reports",
            data=data,
            files=overrides.pop("files", None),
            headers=overrides.pop("headers", None),
        )

    def test_create_report_valid(self):
        response = self.post_report(files={"image": ("photo.png", PNG_BYTES, "image/png")})

        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertEqual(set(body), {"tracking_code", "created_at", "status", "message"})
        self.assertRegex(body["tracking_code"], r"^YT360-[23456789ABCDEFGHJKLMNPQRSTUVWXYZ]{6}$")
        self.assertEqual(body["status"], ReportStatus.NEW.value)
        self.assertIn("message", body)
        self.assertIn("created_at", body)

        with self.SessionTesting() as db:
            report = db.scalar(select(Report).where(Report.tracking_code == body["tracking_code"]))
            self.assertIsNotNone(report)
            self.assertEqual(report.status, ReportStatus.NEW)
            attachment = db.scalar(select(Attachment).where(Attachment.report_id == report.id))
            self.assertIsNotNone(attachment)
            self.assertEqual(attachment.mime_type, "image/png")
            self.assertEqual(attachment.attachment_type, AttachmentType.INITIAL)
            self.assertFalse(attachment.is_public)
            self.assertTrue((self.upload_dir / attachment.stored_filename).exists())
            self.assertNotEqual(attachment.stored_filename, "photo.png")
            self.assertFalse(Path(attachment.stored_filename).is_absolute())

    def test_create_report_without_image_is_allowed(self):
        response = self.post_report()

        self.assertEqual(response.status_code, 201)
        self.assertEqual(self.count_attachments(), 0)

    def test_create_report_accepts_multiple_images(self):
        response = self.post_report(
            files=[
                ("images", ("first.png", PNG_BYTES, "image/png")),
                ("images", ("second.png", PNG_BYTES, "image/png")),
                ("images", ("third.png", PNG_BYTES, "image/png")),
            ]
        )

        self.assertEqual(response.status_code, 201)
        with self.SessionTesting() as db:
            report = db.scalar(select(Report).where(Report.tracking_code == response.json()["tracking_code"]))
            attachments = db.scalars(select(Attachment).where(Attachment.report_id == report.id)).all()
            self.assertEqual(len(attachments), 3)
            self.assertTrue(all(attachment.attachment_type == AttachmentType.INITIAL for attachment in attachments))
            self.assertTrue(all(not attachment.is_public for attachment in attachments))

    def test_public_report_cannot_fake_processing_image_type(self):
        response = self.post_report(
            data={"attachment_type": "AFTER"},
            files={"image": ("after.png", PNG_BYTES, "image/png")},
        )

        self.assertEqual(response.status_code, 201)
        with self.SessionTesting() as db:
            report = db.scalar(select(Report).where(Report.tracking_code == response.json()["tracking_code"]))
            attachment = db.scalar(select(Attachment).where(Attachment.report_id == report.id))
            self.assertEqual(attachment.attachment_type, AttachmentType.INITIAL)
            self.assertFalse(attachment.is_public)

    def test_create_report_accepts_exactly_max_images(self):
        public_api.settings.max_report_images = 5
        files = [("images", (f"photo-{index}.png", PNG_BYTES, "image/png")) for index in range(5)]

        response = self.post_report(files=files)

        self.assertEqual(response.status_code, 201)
        self.assertEqual(self.count_attachments(), 5)

    def test_create_report_rejects_more_than_max_images(self):
        public_api.settings.max_report_images = 2
        before_reports = self.count_reports()
        files = [("images", (f"photo-{index}.png", PNG_BYTES, "image/png")) for index in range(3)]

        response = self.post_report(files=files)

        self.assertEqual(response.status_code, 413)
        self.assertEqual(self.count_reports(), before_reports)
        self.assertEqual(self.count_attachments(), 0)

    def test_create_report_records_technical_metadata_without_public_leak(self):
        response = self.post_report(
            headers={
                "User-Agent": "YT360 Test Browser",
                "X-Forwarded-For": "203.0.113.99",
            }
        )

        self.assertEqual(response.status_code, 201)
        self.assertIn("application/json", response.headers["content-type"])
        tracking_code = response.json()["tracking_code"]
        with self.SessionTesting() as db:
            report = db.scalar(select(Report).where(Report.tracking_code == tracking_code))
            self.assertIsNotNone(report)
            self.assertIsNotNone(report.reporter_ip_hash)
            self.assertEqual(report.reporter_user_agent_hash, hash_technical_value("YT360 Test Browser"))
            self.assertIsNotNone(report.request_fingerprint_hash)
            self.assertIsNotNone(report.client_submitted_at)
            metadata = json.loads(report.technical_metadata)

        self.assertEqual(metadata["client_ip_source"], "direct")
        self.assertFalse(metadata["forwarded_for_used"])
        self.assertTrue(metadata["untrusted_forwarded_header_present"])
        self.assertTrue(metadata["untrusted_forwarded_for_present"])
        self.assertEqual(metadata["user_agent"], "YT360 Test Browser")
        self.assertIn("observed_source_port", metadata)
        self.assertEqual(
            metadata["source_port_note"],
            "Transport metadata only; not a device or person identifier.",
        )

        lookup_response = self.client.get(f"/api/public/reports/{tracking_code}")
        self.assertEqual(lookup_response.status_code, 200)
        self.assertIn("application/json", lookup_response.headers["content-type"])
        lookup_body = lookup_response.json()
        self.assertNotIn("reporter_ip_hash", lookup_body)
        self.assertNotIn("reporter_user_agent_hash", lookup_body)
        self.assertNotIn("request_fingerprint_hash", lookup_body)
        self.assertNotIn("technical_metadata", lookup_body)
        self.assertNotIn("203.0.113.99", lookup_response.text)
        self.assertNotIn("YT360 Test Browser", lookup_response.text)

    def test_trusted_proxy_forwarded_for_is_used_only_for_trusted_peer(self):
        public_api.settings.trusted_proxy_ips = ["10.0.0.0/24"]
        request = SimpleNamespace(
            client=SimpleNamespace(host="10.0.0.10", port=45678),
            headers={
                "x-forwarded-for": "203.0.113.7, 10.0.0.10",
                "user-agent": "Proxy UA",
            },
        )

        metadata = collect_report_technical_metadata(request)

        self.assertEqual(metadata.reporter_ip_hash, hash_technical_value("203.0.113.7"))
        self.assertEqual(metadata.reporter_user_agent_hash, hash_technical_value("Proxy UA"))
        self.assertEqual(metadata.technical_metadata["client_ip_source"], "x-forwarded-for")
        self.assertEqual(metadata.technical_metadata["client_ip"], "203.0.113.7")
        self.assertEqual(metadata.technical_metadata["peer_ip"], "10.0.0.10")
        self.assertEqual(metadata.technical_metadata["user_agent"], "Proxy UA")
        self.assertTrue(metadata.technical_metadata["forwarded_for_used"])
        self.assertEqual(metadata.technical_metadata["observed_source_port"], 45678)

    def test_direct_ip_and_source_port_are_collected_from_peer(self):
        request = SimpleNamespace(
            client=SimpleNamespace(host="198.51.100.23", port=51234),
            headers={"user-agent": "Direct UA"},
        )

        metadata = collect_report_technical_metadata(request)

        self.assertEqual(metadata.reporter_ip_hash, hash_technical_value("198.51.100.23"))
        self.assertEqual(metadata.reporter_user_agent_hash, hash_technical_value("Direct UA"))
        self.assertEqual(metadata.technical_metadata["client_ip"], "198.51.100.23")
        self.assertEqual(metadata.technical_metadata["client_ip_source"], "direct")
        self.assertEqual(metadata.technical_metadata["observed_source_port"], 51234)

    def test_source_port_is_none_when_not_observed(self):
        request = SimpleNamespace(
            client=SimpleNamespace(host="198.51.100.23", port=None),
            headers={"user-agent": "No Port UA"},
        )

        metadata = collect_report_technical_metadata(request)

        self.assertIsNone(metadata.technical_metadata["observed_source_port"])
        self.assertEqual(
            metadata.technical_metadata["source_port_note"],
            "Transport metadata only; not a device or person identifier.",
        )

    def test_untrusted_forwarded_headers_are_ignored(self):
        public_api.settings.trusted_proxy_ips = []
        request = SimpleNamespace(
            client=SimpleNamespace(host="198.51.100.23", port=51234),
            headers={
                "x-forwarded-for": "203.0.113.7",
                "x-real-ip": "203.0.113.8",
                "user-agent": "Untrusted UA",
            },
        )

        metadata = collect_report_technical_metadata(request)

        self.assertEqual(metadata.reporter_ip_hash, hash_technical_value("198.51.100.23"))
        self.assertEqual(metadata.technical_metadata["client_ip"], "198.51.100.23")
        self.assertEqual(metadata.technical_metadata["client_ip_source"], "direct")
        self.assertTrue(metadata.technical_metadata["untrusted_forwarded_header_present"])
        self.assertTrue(metadata.technical_metadata["untrusted_real_ip_present"])

    def test_trusted_proxy_real_ip_is_used_when_forwarded_for_absent(self):
        public_api.settings.trusted_proxy_ips = ["10.0.0.0/24"]
        request = SimpleNamespace(
            client=SimpleNamespace(host="10.0.0.10", port=45678),
            headers={
                "x-real-ip": "203.0.113.8",
                "user-agent": "Real IP UA",
            },
        )

        metadata = collect_report_technical_metadata(request)

        self.assertEqual(metadata.reporter_ip_hash, hash_technical_value("203.0.113.8"))
        self.assertEqual(metadata.technical_metadata["client_ip"], "203.0.113.8")
        self.assertEqual(metadata.technical_metadata["client_ip_source"], "x-real-ip")
        self.assertFalse(metadata.technical_metadata["forwarded_for_used"])

    def test_user_agent_is_limited_before_storage(self):
        long_user_agent = "A" * (USER_AGENT_MAX_LENGTH + 25)
        request = SimpleNamespace(
            client=SimpleNamespace(host="198.51.100.23", port=51234),
            headers={"user-agent": long_user_agent},
        )

        metadata = collect_report_technical_metadata(request)

        self.assertEqual(len(metadata.technical_metadata["user_agent"]), USER_AGENT_MAX_LENGTH)
        self.assertEqual(
            metadata.reporter_user_agent_hash,
            hash_technical_value(long_user_agent[:USER_AGENT_MAX_LENGTH]),
        )

    def test_create_report_rejects_invalid_category(self):
        before = self.count_reports()
        response = self.post_report(data={"category_id": "999999"})

        self.assertEqual(response.status_code, 404)
        self.assertEqual(self.count_reports(), before)

    def test_create_report_rejects_inactive_category(self):
        before = self.count_reports()
        response = self.post_report(data={"category_id": str(self.inactive_category_id)})

        self.assertEqual(response.status_code, 404)
        self.assertEqual(self.count_reports(), before)

    def test_create_report_rejects_invalid_area(self):
        before = self.count_reports()
        response = self.post_report(data={"area_id": "999999"})

        self.assertEqual(response.status_code, 404)
        self.assertEqual(self.count_reports(), before)

    def test_create_report_rejects_inactive_area(self):
        before = self.count_reports()
        response = self.post_report(data={"area_id": str(self.inactive_area_id)})

        self.assertEqual(response.status_code, 404)
        self.assertEqual(self.count_reports(), before)

    def test_create_report_rejects_empty_description(self):
        before = self.count_reports()
        response = self.post_report(data={"description": "   "})

        self.assertEqual(response.status_code, 422)
        self.assertEqual(self.count_reports(), before)

    def test_create_report_rejects_too_long_description(self):
        before = self.count_reports()
        response = self.post_report(data={"description": "x" * (public_api.DESCRIPTION_MAX_LENGTH + 1)})

        self.assertEqual(response.status_code, 422)
        self.assertEqual(self.count_reports(), before)

    def test_create_report_rejects_non_image_file(self):
        before_reports = self.count_reports()
        before_attachments = self.count_attachments()
        response = self.post_report(files={"image": ("note.txt", b"not an image", "text/plain")})

        self.assertEqual(response.status_code, 415)
        self.assertEqual(self.count_reports(), before_reports)
        self.assertEqual(self.count_attachments(), before_attachments)
        self.assertFalse(self.upload_dir.exists())

    def test_create_report_rejects_image_mime_with_wrong_extension(self):
        before_reports = self.count_reports()
        response = self.post_report(files={"image": ("photo.exe", PNG_BYTES, "image/png")})

        self.assertEqual(response.status_code, 415)
        self.assertEqual(self.count_reports(), before_reports)
        self.assertFalse(self.upload_dir.exists())

    def test_create_report_rejects_bad_signature(self):
        before_reports = self.count_reports()
        response = self.post_report(files={"image": ("photo.png", b"not a png", "image/png")})

        self.assertEqual(response.status_code, 415)
        self.assertEqual(self.count_reports(), before_reports)
        self.assertFalse(self.upload_dir.exists())

    def test_create_report_rejects_oversized_upload(self):
        public_api.settings.max_upload_bytes = 12
        before_reports = self.count_reports()
        response = self.post_report(files={"image": ("photo.png", PNG_BYTES, "image/png")})

        self.assertEqual(response.status_code, 413)
        self.assertEqual(self.count_reports(), before_reports)
        self.assertFalse(self.upload_dir.exists())

    def test_upload_filename_path_traversal_is_not_used(self):
        response = self.post_report(files={"image": ("../../evil.png", PNG_BYTES, "image/png")})

        if response.status_code == 201:
            with self.SessionTesting() as db:
                report = db.scalar(select(Report).where(Report.tracking_code == response.json()["tracking_code"]))
                attachment = db.scalar(select(Attachment).where(Attachment.report_id == report.id))
                stored_path = (self.upload_dir / attachment.stored_filename).resolve()
                self.assertTrue(stored_path.exists())
                self.assertEqual(stored_path.parent, self.upload_dir.resolve())
                self.assertNotIn("evil", attachment.stored_filename)
        else:
            self.assertEqual(response.status_code, 415)
            self.assertFalse(self.upload_dir.exists())

    def test_create_report_rejects_path_traversal_in_multiple_images(self):
        before_reports = self.count_reports()
        response = self.post_report(files=[("images", ("..\\evil.png", PNG_BYTES, "image/png"))])

        self.assertEqual(response.status_code, 415)
        self.assertEqual(self.count_reports(), before_reports)
        self.assertFalse(self.upload_dir.exists())

    def test_tracking_code_is_unique(self):
        responses = [self.post_report() for _ in range(20)]

        self.assertTrue(all(response.status_code == 201 for response in responses))
        tracking_codes = [response.json()["tracking_code"] for response in responses]
        self.assertEqual(len(set(tracking_codes)), 20)

        with self.SessionTesting() as db:
            db_codes = set(db.scalars(select(Report.tracking_code)).all())
            self.assertTrue(set(tracking_codes).issubset(db_codes))

    def test_similar_recent_report_creates_duplicate_warning_only(self):
        first = self.post_report(data={"description": "Cay do chan mot phan duong can xu ly som."})
        second = self.post_report(data={"description": "Cay do chan duong can xu ly som tai khu vuc nay."})

        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 201)
        with self.SessionTesting() as db:
            report = db.scalar(select(Report).where(Report.tracking_code == second.json()["tracking_code"]))
            links = db.scalars(select(ReportDuplicateLink).where(ReportDuplicateLink.report_id == report.id)).all()
            self.assertTrue(report.is_duplicate)
            self.assertEqual(len(links), 1)
            self.assertEqual(links[0].status, DuplicateLinkStatus.SUGGESTED)
            self.assertGreaterEqual(links[0].score, public_api.settings.duplicate_similarity_threshold)

    def test_same_category_different_area_is_not_marked_duplicate(self):
        other_area_id = self.create_active_area()
        self.assertEqual(self.post_report(data={"description": "Mat nap cong bi vo can sua gap."}).status_code, 201)
        response = self.post_report(
            data={
                "area_id": str(other_area_id),
                "description": "Mat nap cong bi vo can sua gap.",
            }
        )

        self.assertEqual(response.status_code, 201)
        with self.SessionTesting() as db:
            report = db.scalar(select(Report).where(Report.tracking_code == response.json()["tracking_code"]))
            self.assertFalse(report.is_duplicate)
        self.assertEqual(self.count_duplicate_links(), 0)

    def test_same_area_different_category_is_not_marked_duplicate(self):
        other_category_id = self.create_active_category()
        self.assertEqual(self.post_report(data={"description": "Rac thai tap ket sai noi quy."}).status_code, 201)
        response = self.post_report(
            data={
                "category_id": str(other_category_id),
                "description": "Rac thai tap ket sai noi quy.",
            }
        )

        self.assertEqual(response.status_code, 201)
        with self.SessionTesting() as db:
            report = db.scalar(select(Report).where(Report.tracking_code == response.json()["tracking_code"]))
            self.assertFalse(report.is_duplicate)
        self.assertEqual(self.count_duplicate_links(), 0)

    def test_old_similar_report_outside_window_is_not_marked_duplicate(self):
        public_api.settings.duplicate_detection_window_hours = 1
        with self.SessionTesting() as db:
            db.add(
                Report(
                    tracking_code="YT360-OLD111",
                    category_id=self.category_id,
                    area_id=self.area_id,
                    description="Den duong hu hong can sua gap.",
                    status=ReportStatus.NEW,
                    created_at=datetime.now(timezone.utc) - timedelta(hours=3),
                )
            )
            db.commit()

        response = self.post_report(data={"description": "Den duong hu hong can sua gap."})

        self.assertEqual(response.status_code, 201)
        with self.SessionTesting() as db:
            report = db.scalar(select(Report).where(Report.tracking_code == response.json()["tracking_code"]))
            self.assertFalse(report.is_duplicate)
        self.assertEqual(self.count_duplicate_links(), 0)

    def test_rate_limit_rejects_excess_requests(self):
        public_api.settings.public_report_rate_limit = 2
        public_api.settings.public_report_rate_limit_window_seconds = 60
        public_api.settings.public_report_spam_flag_threshold = 10
        public_report_limiter.reset()
        public_report_rapid_limiter.reset()

        self.assertEqual(self.post_report().status_code, 201)
        self.assertEqual(self.post_report().status_code, 201)
        response = self.post_report()

        self.assertEqual(response.status_code, 429)
        self.assertNotIn("password", response.text.lower())
        self.assertNotIn("traceback", response.text.lower())

    def test_rate_limit_window_expiry_allows_new_report(self):
        public_api.settings.public_report_rate_limit = 2
        public_api.settings.public_report_rate_limit_window_seconds = 60
        public_api.settings.public_report_spam_flag_threshold = 10
        public_report_limiter.reset()
        public_report_rapid_limiter.reset()

        with patch("app.core.rate_limit.monotonic", side_effect=[0, 0, 1, 1, 61, 61]):
            self.assertEqual(self.post_report(data={"description": "Window 1"}).status_code, 201)
            self.assertEqual(self.post_report(data={"description": "Window 2"}).status_code, 201)
            response = self.post_report(data={"description": "Window 3"})

        self.assertEqual(response.status_code, 201)

    def test_untrusted_forwarded_for_does_not_bypass_ip_rate_limit(self):
        public_api.settings.trusted_proxy_ips = []
        public_api.settings.public_report_rate_limit = 2
        public_api.settings.public_report_rate_limit_window_seconds = 60
        public_api.settings.public_report_spam_flag_threshold = 10
        public_report_limiter.reset()
        public_report_rapid_limiter.reset()

        self.assertEqual(self.post_report(headers={"X-Forwarded-For": "203.0.113.1"}).status_code, 201)
        self.assertEqual(self.post_report(headers={"X-Forwarded-For": "203.0.113.2"}).status_code, 201)
        response = self.post_report(headers={"X-Forwarded-For": "203.0.113.3"})

        self.assertEqual(response.status_code, 429)

    def test_different_rate_limit_keys_do_not_share_counter(self):
        public_api.settings.public_report_rate_limit = 1
        public_report_limiter.reset()

        public_report_limiter.check("ip-a", limit=1, window_seconds=60)
        public_report_limiter.check("ip-b", limit=1, window_seconds=60)

        with self.assertRaises(Exception):
            public_report_limiter.check("ip-a", limit=1, window_seconds=60)

    def test_rapid_repeated_reports_are_flagged_not_blocked_when_under_rate_limit(self):
        public_api.settings.public_report_rate_limit = 100
        public_api.settings.public_report_rapid_limit = 10
        public_api.settings.public_report_spam_flag_threshold = 2
        public_report_limiter.reset()
        public_report_rapid_limiter.reset()

        first = self.post_report()
        second = self.post_report()

        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 201)
        with self.SessionTesting() as db:
            first_report = db.scalar(select(Report).where(Report.tracking_code == first.json()["tracking_code"]))
            second_report = db.scalar(select(Report).where(Report.tracking_code == second.json()["tracking_code"]))
            self.assertFalse(first_report.is_spam)
            self.assertTrue(second_report.is_spam)
            self.assertGreaterEqual(second_report.spam_score, 0.7)
            self.assertEqual(second_report.moderation_status, "FLAGGED")
            self.assertIn("anti_spam", json.loads(second_report.technical_metadata))

    def test_rapid_limit_rejects_after_burst_threshold(self):
        public_api.settings.public_report_rate_limit = 100
        public_api.settings.public_report_rapid_limit = 2
        public_api.settings.public_report_spam_flag_threshold = 2
        public_report_limiter.reset()
        public_report_rapid_limiter.reset()

        self.assertEqual(self.post_report().status_code, 201)
        self.assertEqual(self.post_report().status_code, 201)
        response = self.post_report()

        self.assertEqual(response.status_code, 429)
        self.assertIn("application/json", response.headers["content-type"])
        self.assertNotIn("<!doctype", response.text.lower())

    def test_active_source_block_rejects_new_report_without_creating_data(self):
        public_api.settings.trusted_proxy_ips = []
        blocked_ip_hash = hash_technical_value("testclient")
        with self.SessionTesting() as db:
            db.add(ReportSourceBlock(source_type="IP", source_hash=blocked_ip_hash, reason="Test block"))
            db.commit()
        before = self.count_reports()

        response = self.post_report(headers={"User-Agent": "Blocked UA"})

        self.assertEqual(response.status_code, 429)
        self.assertEqual(self.count_reports(), before)

    def test_rate_limiter_is_thread_safe_under_concurrent_requests(self):
        public_report_limiter.reset()

        def record_request(_index):
            return public_report_limiter.record("concurrent-test", 60)

        with ThreadPoolExecutor(max_workers=8) as executor:
            counts = list(executor.map(record_request, range(20)))

        self.assertEqual(sorted(counts), list(range(1, 21)))

    def test_concurrent_report_requests_respect_rate_limit_without_race(self):
        public_api.settings.public_report_rate_limit = 5
        public_api.settings.public_report_rate_limit_window_seconds = 60
        public_api.settings.public_report_spam_flag_threshold = 20
        public_report_limiter.reset()
        public_report_rapid_limiter.reset()

        def submit_report(index):
            return self.post_report(data={"description": f"Concurrent report {index}"}).status_code

        with ThreadPoolExecutor(max_workers=8) as executor:
            statuses = list(executor.map(submit_report, range(8)))

        self.assertEqual(statuses.count(201), 5)
        self.assertEqual(statuses.count(429), 3)
        self.assertEqual(self.count_reports(), 5)

    def create_report_for_lookup(self, status=ReportStatus.COORDINATING):
        with self.SessionTesting() as db:
            user = User(
                username="admin",
                password_hash="not-a-plain-password-hash",
                full_name="Admin Development",
                role="admin",
                is_active=True,
            )
            report = Report(
                tracking_code="YT360-7K9M2Q",
                category_id=self.category_id,
                area_id=self.area_id,
                description="Nội dung công dân gửi không trả public ở bước này.",
                status=status,
                public_response="Đơn vị phụ trách đang phối hợp xử lý.",
                internal_note="Ghi chú nội bộ tuyệt đối không trả ra public.",
            )
            db.add_all([user, report])
            db.flush()
            db.add_all(
                [
                    StatusHistory(
                        report_id=report.id,
                        old_status=ReportStatus.NEW,
                        new_status=ReportStatus.RECEIVED,
                        public_note="Đã tiếp nhận phản ánh.",
                        internal_note="Ghi chú nội bộ trạng thái 1.",
                        changed_by=user.id,
                    ),
                    StatusHistory(
                        report_id=report.id,
                        old_status=ReportStatus.RECEIVED,
                        new_status=ReportStatus.COORDINATING,
                        public_note="Đang phối hợp kiểm tra.",
                        internal_note="Ghi chú nội bộ trạng thái 2.",
                        changed_by=user.id,
                    ),
                    AuditLog(
                        user_id=user.id,
                        action="report.lookup.test",
                        entity_type="report",
                        entity_id=report.id,
                        details="Audit log không được trả ra public.",
                    ),
                ]
            )
            db.commit()
            return report.tracking_code

    def test_lookup_report_returns_public_data_only(self):
        tracking_code = self.create_report_for_lookup()

        response = self.client.get(f"/api/public/reports/{tracking_code.lower()}")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(
            set(body),
            {
                "tracking_code",
                "category",
                "area",
                "created_at",
                "updated_at",
                "public_status",
                "public_response",
                "public_status_history",
            },
        )
        self.assertEqual(body["tracking_code"], tracking_code)
        with self.SessionTesting() as db:
            category_name = db.scalar(select(Category.name).where(Category.id == self.category_id))
            area_name = db.scalar(select(Area.name).where(Area.id == self.area_id))
        self.assertEqual(body["category"], category_name)
        self.assertEqual(body["area"], area_name)
        self.assertEqual(body["public_status"]["code"], ReportStatus.COORDINATING.value)
        self.assertEqual(body["public_status"]["label"], "Đang phối hợp")
        self.assertEqual(body["public_response"], "Đơn vị phụ trách đang phối hợp xử lý.")
        self.assertEqual(
            [item["public_status"]["code"] for item in body["public_status_history"]],
            [ReportStatus.RECEIVED.value, ReportStatus.COORDINATING.value],
        )

        serialized = response.text.lower()
        forbidden_fragments = [
            "internal_note",
            "audit",
            "user",
            "admin",
            "password",
            "token",
            "changed_by",
            "ghi chú nội bộ",
        ]
        for fragment in forbidden_fragments:
            self.assertNotIn(fragment, serialized)

    def test_lookup_report_without_status_history_returns_current_public_status(self):
        with self.SessionTesting() as db:
            report = Report(
                tracking_code="YT360-7K9M2Q",
                category_id=self.category_id,
                area_id=self.area_id,
                description="Không có lịch sử trạng thái.",
                status=ReportStatus.NEW,
            )
            db.add(report)
            db.commit()

        response = self.client.get("/api/public/reports/YT360-7K9M2Q")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["public_status"]["code"], ReportStatus.NEW.value)
        self.assertEqual(len(body["public_status_history"]), 1)
        self.assertEqual(body["public_status_history"][0]["public_status"]["code"], ReportStatus.NEW.value)

    def test_lookup_report_not_found_is_polite_and_generic(self):
        response = self.client.get("/api/public/reports/YT360-ZZZZZZ")

        self.assertEqual(response.status_code, 404)
        self.assertIn("Không tìm thấy phản ánh", response.json()["detail"])
        self.assertNotIn("traceback", response.text.lower())
        self.assertNotIn("sql", response.text.lower())
        self.assertNotIn("internal", response.text.lower())

    def test_lookup_report_rejects_invalid_tracking_code_format(self):
        invalid_codes = [
            "YT360-TOO-LONG",
            "YT360-!!!!!!",
            "WRONG-7K9M2Q",
            "YT360-ABC",
        ]

        for code in invalid_codes:
            with self.subTest(code=code):
                response = self.client.get(f"/api/public/reports/{code}")
                self.assertEqual(response.status_code, 422)
                self.assertIn("Mã tra cứu không hợp lệ", response.json()["detail"])
                self.assertNotIn("traceback", response.text.lower())

    def test_lookup_rate_limit_rejects_excess_requests(self):
        public_api.settings.public_lookup_rate_limit = 2
        public_api.settings.public_lookup_rate_limit_window_seconds = 60
        public_lookup_limiter.reset()
        tracking_code = self.create_report_for_lookup()

        self.assertEqual(self.client.get(f"/api/public/reports/{tracking_code}").status_code, 200)
        self.assertEqual(self.client.get(f"/api/public/reports/{tracking_code}").status_code, 200)
        response = self.client.get(f"/api/public/reports/{tracking_code}")

        self.assertEqual(response.status_code, 429)
        self.assertNotIn("traceback", response.text.lower())


if __name__ == "__main__":
    unittest.main()
