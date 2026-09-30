import enum
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
    true,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class ReportStatus(str, enum.Enum):
    NEW = "NEW"
    RECEIVED = "RECEIVED"
    COORDINATING = "COORDINATING"
    RESOLVED = "RESOLVED"
    OUT_OF_SCOPE = "OUT_OF_SCOPE"


status_enum = Enum(
    ReportStatus,
    name="report_status",
    native_enum=False,
    length=32,
    validate_strings=True,
)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(80), nullable=False, unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(150), nullable=False)
    role: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    status_changes: Mapped[list["StatusHistory"]] = relationship(back_populates="changed_by_user")
    audit_logs: Mapped[list["AuditLog"]] = relationship(back_populates="user")


class Category(Base):
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False, unique=True)
    icon: Mapped[str | None] = mapped_column(String(80), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true(), index=True)
    display_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0", index=True)

    reports: Mapped[list["Report"]] = relationship(back_populates="category")


class Area(Base):
    __tablename__ = "areas"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False, unique=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true(), index=True)
    display_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0", index=True)

    reports: Mapped[list["Report"]] = relationship(back_populates="area")


class Report(Base):
    __tablename__ = "reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tracking_code: Mapped[str] = mapped_column(String(40), nullable=False, unique=True, index=True)
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id", ondelete="RESTRICT"), nullable=False, index=True)
    area_id: Mapped[int | None] = mapped_column(ForeignKey("areas.id", ondelete="SET NULL"), nullable=True, index=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[ReportStatus] = mapped_column(
        status_enum,
        nullable=False,
        default=ReportStatus.NEW,
        server_default=ReportStatus.NEW.value,
        index=True,
    )
    public_response: Mapped[str | None] = mapped_column(Text, nullable=True)
    internal_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), index=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    category: Mapped[Category] = relationship(back_populates="reports")
    area: Mapped[Area | None] = relationship(back_populates="reports")
    attachments: Mapped[list["Attachment"]] = relationship(back_populates="report", cascade="all, delete-orphan")
    status_history: Mapped[list["StatusHistory"]] = relationship(back_populates="report", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_reports_status_created_at", "status", "created_at"),
        Index("ix_reports_category_status", "category_id", "status"),
    )


class Attachment(Base):
    __tablename__ = "attachments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    report_id: Mapped[int] = mapped_column(ForeignKey("reports.id", ondelete="CASCADE"), nullable=False, index=True)
    stored_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(120), nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    report: Mapped[Report] = relationship(back_populates="attachments")


class StatusHistory(Base):
    __tablename__ = "status_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    report_id: Mapped[int] = mapped_column(ForeignKey("reports.id", ondelete="CASCADE"), nullable=False, index=True)
    old_status: Mapped[ReportStatus | None] = mapped_column(status_enum, nullable=True)
    new_status: Mapped[ReportStatus] = mapped_column(status_enum, nullable=False, index=True)
    public_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    internal_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    changed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), index=True)

    report: Mapped[Report] = relationship(back_populates="status_history")
    changed_by_user: Mapped[User | None] = relationship(back_populates="status_changes")

    __table_args__ = (
        Index("ix_status_history_report_created_at", "report_id", "created_at"),
    )


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    entity_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    details: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), index=True)

    user: Mapped[User | None] = relationship(back_populates="audit_logs")

    __table_args__ = (
        Index("ix_audit_logs_entity", "entity_type", "entity_id"),
    )
