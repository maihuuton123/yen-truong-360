import unittest

from app.db.base import Base
from app.models import AdditionalInfoRequestStatus, NotificationStatus, ReportPriority, ReportStatus


class DatabaseModelTests(unittest.TestCase):
    def test_core_tables_are_registered(self):
        expected_tables = {
            "users",
            "categories",
            "areas",
            "reports",
            "attachments",
            "status_history",
            "report_assignment_history",
            "report_internal_notes",
            "additional_info_requests",
            "notifications",
            "audit_logs",
        }

        self.assertTrue(expected_tables.issubset(set(Base.metadata.tables)))

    def test_report_status_values(self):
        self.assertEqual(
            [status.value for status in ReportStatus],
            ["NEW", "RECEIVED", "COORDINATING", "RESOLVED", "OUT_OF_SCOPE"],
        )

    def test_v2_report_fields_are_registered_without_replacing_v1_fields(self):
        reports_table = Base.metadata.tables["reports"]
        report_columns = set(reports_table.columns.keys())

        self.assertTrue(
            {
                "priority",
                "assigned_to",
                "assigned_at",
                "deadline_at",
                "public_response",
                "internal_note",
                "location_text",
                "location_latitude",
                "location_longitude",
                "location_accuracy_meters",
                "is_duplicate",
                "duplicate_of_report_id",
                "is_spam",
                "spam_score",
                "spam_reason",
                "moderation_status",
                "reporter_ip_hash",
                "reporter_user_agent_hash",
                "request_fingerprint_hash",
                "submission_source",
                "client_submitted_at",
                "technical_metadata",
            }.issubset(report_columns)
        )

        report_foreign_keys = {
            (foreign_key.parent.name, foreign_key.column.table.name, foreign_key.column.name)
            for foreign_key in reports_table.foreign_keys
        }
        self.assertTrue(
            {
                ("category_id", "categories", "id"),
                ("area_id", "areas", "id"),
                ("assigned_to", "users", "id"),
                ("duplicate_of_report_id", "reports", "id"),
            }.issubset(report_foreign_keys)
        )

    def test_v2_status_values_do_not_add_sms_or_otp_authentication(self):
        self.assertEqual([priority.value for priority in ReportPriority], ["LOW", "NORMAL", "HIGH", "URGENT"])
        self.assertEqual(
            [status.value for status in AdditionalInfoRequestStatus],
            ["OPEN", "RESPONDED", "CLOSED", "CANCELLED"],
        )
        self.assertEqual(
            [status.value for status in NotificationStatus],
            ["PENDING", "SENT", "FAILED", "CANCELLED"],
        )
        channel_default = str(Base.metadata.tables["notifications"].columns["channel"].server_default.arg).upper()
        self.assertIn("IN_APP", channel_default)
        self.assertNotIn("SMS", channel_default)


if __name__ == "__main__":
    unittest.main()
