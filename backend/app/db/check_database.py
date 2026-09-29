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
    "audit_logs",
    "alembic_version",
}


def check_database() -> None:
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    missing = EXPECTED_TABLES - tables
    if missing:
        raise RuntimeError(f"Missing tables: {', '.join(sorted(missing))}")

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
