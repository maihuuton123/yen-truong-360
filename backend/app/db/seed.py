import os

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import hash_password
from app.db.session import SessionLocal
from app.models import Area, Category, User


CATEGORIES = [
    ("Giao thông – vật cản", "traffic"),
    ("Nguy cơ cháy, nổ", "fire"),
    ("Nguy cơ đuối nước", "water"),
    ("An toàn khu vực trường học", "school"),
    ("Trật tự – dân sinh", "community"),
    ("Nguy cơ mất an toàn khác", "warning"),
]

DEMO_AREAS = [
    "Khu vực demo 1",
    "Khu vực demo 2",
    "Khu vực demo 3",
    "Khu vực demo 4",
]


def require_admin_password() -> str:
    password = settings.admin_password or os.getenv("ADMIN_PASSWORD")
    if not password:
        raise RuntimeError("ADMIN_PASSWORD is required before running the database seed.")
    return password


def seed_categories(db: Session) -> None:
    for index, (name, icon) in enumerate(CATEGORIES, start=1):
        category = db.scalar(select(Category).where(Category.name == name))
        if category is None:
            db.add(Category(name=name, icon=icon, display_order=index, is_active=True))
            continue

        category.icon = icon
        category.display_order = index
        category.is_active = True


def seed_areas(db: Session) -> None:
    for index, name in enumerate(DEMO_AREAS, start=1):
        area = db.scalar(select(Area).where(Area.name == name))
        if area is None:
            db.add(Area(name=name, display_order=index, is_active=True))
            continue

        area.display_order = index
        area.is_active = True


def seed_admin(db: Session) -> None:
    password = require_admin_password()
    user = db.scalar(select(User).where(User.username == settings.admin_username))

    if user is None:
        db.add(
            User(
                username=settings.admin_username,
                password_hash=hash_password(password),
                full_name="Quản trị phát triển",
                role="ADMIN",
                is_active=True,
            )
        )
        return

    user.password_hash = hash_password(password)
    user.full_name = "Quản trị phát triển"
    user.role = "ADMIN"
    user.is_active = True


def seed_database() -> None:
    with SessionLocal() as db:
        seed_categories(db)
        seed_areas(db)
        seed_admin(db)
        db.commit()


if __name__ == "__main__":
    seed_database()
    print("Database seed completed.")
