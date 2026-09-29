import unittest

from app.db.base import Base
from app.models import ReportStatus


class DatabaseModelTests(unittest.TestCase):
    def test_core_tables_are_registered(self):
        expected_tables = {
            "users",
            "categories",
            "areas",
            "reports",
            "attachments",
            "status_history",
            "audit_logs",
        }

        self.assertTrue(expected_tables.issubset(set(Base.metadata.tables)))

    def test_report_status_values(self):
        self.assertEqual(
            [status.value for status in ReportStatus],
            ["NEW", "RECEIVED", "COORDINATING", "RESOLVED", "OUT_OF_SCOPE"],
        )


if __name__ == "__main__":
    unittest.main()
