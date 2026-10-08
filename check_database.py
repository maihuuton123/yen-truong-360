from sqlalchemy import func, inspect, select

from app.db.session import engine, SessionLocal
from app.models import Area, Category, User


EXPECTED_TABLES = {
    "users",
    "categories",
    "areas",
    "reports",
    "attachments",
    "status_history",
    "report_source_blocks",
    "report_duplicate_links",
    "report_assignment_history",
    "report_internal_notes",
    "additional_info_requests",
    "notifications",
    "audit_logs",
    "alembic_version",
}

EXPECTED_REPORT_FOREIGN_KEYS = {
    ("category_id", "categories", "id"),
    ("area_id", "areas", "id"),
    ("assigned_to", "users", "id"),
    ("duplicate_of_report_id", "reports", "id"),
}


def check_database() -> None:
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    missing = EXPECTED_TABLES - tables
    if missing:
        raise RuntimeError(f"Missing tables: {', '.join(sorted(missing))}")

    report_foreign_keys = {
        (foreign_key["constrained_columns"][0], foreign_key["referred_table"], foreign_key["referred_columns"][0])
        for foreign_key in inspector.get_foreign_keys("reports")
        if foreign_key["constrained_columns"] and foreign_key["referred_columns"]
    }
    missing_report_foreign_keys = EXPECTED_REPORT_FOREIGN_KEYS - report_foreign_keys
    if missing_report_foreign_keys:
        formatted = [
            f"reports.{column} -> {table}.{target_column}"
            for column, table, target_column in sorted(missing_report_foreign_keys)
        ]
        raise RuntimeError(f"Missing report foreign keys: {', '.join(formatted)}")

    with SessionLocal() as db:
        category_count = db.scalar(select(func.count()).select_from(Category))
        area_count = db.scalar(select(func.count()).select_from(Area))
        admin_count = db.scalar(select(func.count()).select_from(User).where(User.role == "ADMIN"))

    print(f"Tables OK: {', '.join(sorted(EXPECTED_TABLES))}")
    print(f"Categories: {category_count}")
    print(f"Areas: {area_count}")
    print(f"Admin users: {admin_count}")


if __name__ == "__main__":
    check_database()
