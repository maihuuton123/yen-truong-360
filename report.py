import enum
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    false,
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


class ReportPriority(str, enum.Enum):
    LOW = "LOW"
    NORMAL = "NORMAL"
    HIGH = "HIGH"
    URGENT = "URGENT"


class AdditionalInfoRequestStatus(str, enum.Enum):
    OPEN = "OPEN"
    RESPONDED = "RESPONDED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class NotificationStatus(str, enum.Enum):
    PENDING = "PENDING"
    SENT = "SENT"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


status_enum = Enum(
    ReportStatus,
    name="report_status",
    native_enum=False,
    length=32,
    validate_strings=True,
)

priority_enum = Enum(
    ReportPriority,
    name="report_priority",
    native_enum=False,
    length=32,
    validate_strings=True,
)

additional_info_request_status_enum = Enum(
    AdditionalInfoRequestStatus,
    name="additional_info_request_status",
    native_enum=False,
    length=32,
    validate_strings=True,
)

notification_status_enum = Enum(
    NotificationStatus,
    name="notification_status",
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
    assigned_reports: Mapped[list["Report"]] = relationship(back_populates="assigned_to_user")
    assignment_changes: Mapped[list["ReportAssignmentHistory"]] = relationship(
        back_populates="changed_by_user",
        foreign_keys="ReportAssignmentHistory.changed_by",
    )
    internal_notes: Mapped[list["ReportInternalNote"]] = relationship(back_populates="author_user")
    additional_info_requests: Mapped[list["AdditionalInfoRequest"]] = relationship(back_populates="requested_by_user")
    notifications: Mapped[list["Notification"]] = relationship(back_populates="recipient_user")


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
    priority: Mapped[ReportPriority] = mapped_column(
        priority_enum,
        nullable=False,
        default=ReportPriority.NORMAL,
        server_default=ReportPriority.NORMAL.value,
        index=True,
    )
    assigned_to: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    assigned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deadline_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    public_response: Mapped[str | None] = mapped_column(Text, nullable=True)
    internal_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    location_text: Mapped[str | None] = mapped_column(String(500), nullable=True)
    location_latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    location_longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    location_accuracy_meters: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_duplicate: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false(), index=True)
    duplicate_of_report_id: Mapped[int | None] = mapped_column(
        ForeignKey("reports.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    is_spam: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false(), index=True)
    spam_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    spam_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    moderation_status: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        default="UNREVIEWED",
        server_default="UNREVIEWED",
        index=True,
    )
    reporter_ip_hash: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    reporter_user_agent_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    request_fingerprint_hash: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    submission_source: Mapped[str] = mapped_column(
        String(60),
        nullable=False,
        default="public_form",
        server_default="public_form",
        index=True,
    )
    client_submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    technical_metadata: Mapped[str | None] = mapped_column("technical_metadata", Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), index=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    category: Mapped[Category] = relationship(back_populates="reports")
    area: Mapped[Area | None] = relationship(back_populates="reports")
    assigned_to_user: Mapped[User | None] = relationship(back_populates="assigned_reports", foreign_keys=[assigned_to])
    duplicate_of_report: Mapped["Report | None"] = relationship(remote_side=[id], foreign_keys=[duplicate_of_report_id])
    attachments: Mapped[list["Attachment"]] = relationship(back_populates="report", cascade="all, delete-orphan")
    status_history: Mapped[list["StatusHistory"]] = relationship(back_populates="report", cascade="all, delete-orphan")
    assignment_history: Mapped[list["ReportAssignmentHistory"]] = relationship(back_populates="report", cascade="all, delete-orphan")
    internal_notes: Mapped[list["ReportInternalNote"]] = relationship(back_populates="report", cascade="all, delete-orphan")
    additional_info_requests: Mapped[list["AdditionalInfoRequest"]] = relationship(back_populates="report", cascade="all, delete-orphan")
    notifications: Mapped[list["Notification"]] = relationship(back_populates="report", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_reports_status_created_at", "status", "created_at"),
        Index("ix_reports_category_status", "category_id", "status"),
        Index("ix_reports_priority_deadline", "priority", "deadline_at"),
        Index("ix_reports_assigned_status", "assigned_to", "status"),
        Index("ix_reports_spam_duplicate", "is_spam", "is_duplicate"),
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


class ReportAssignmentHistory(Base):
    __tablename__ = "report_assignment_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    report_id: Mapped[int] = mapped_column(ForeignKey("reports.id", ondelete="CASCADE"), nullable=False, index=True)
    old_assigned_to: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    new_assigned_to: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    old_priority: Mapped[ReportPriority | None] = mapped_column(priority_enum, nullable=True)
    new_priority: Mapped[ReportPriority | None] = mapped_column(priority_enum, nullable=True)
    old_deadline_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    new_deadline_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    changed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), index=True)

    report: Mapped[Report] = relationship(back_populates="assignment_history")
    old_assigned_to_user: Mapped[User | None] = relationship(foreign_keys=[old_assigned_to])
    new_assigned_to_user: Mapped[User | None] = relationship(foreign_keys=[new_assigned_to])
    changed_by_user: Mapped[User | None] = relationship(back_populates="assignment_changes", foreign_keys=[changed_by])

    __table_args__ = (
        Index("ix_report_assignment_history_report_created_at", "report_id", "created_at"),
    )


class ReportInternalNote(Base):
    __tablename__ = "report_internal_notes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    report_id: Mapped[int] = mapped_column(ForeignKey("reports.id", ondelete="CASCADE"), nullable=False, index=True)
    author_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    note: Mapped[str] = mapped_column(Text, nullable=False)
    is_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false(), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    report: Mapped[Report] = relationship(back_populates="internal_notes")
    author_user: Mapped[User | None] = relationship(back_populates="internal_notes")

    __table_args__ = (
        Index("ix_report_internal_notes_report_created_at", "report_id", "created_at"),
    )


class AdditionalInfoRequest(Base):
    __tablename__ = "additional_info_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    report_id: Mapped[int] = mapped_column(ForeignKey("reports.id", ondelete="CASCADE"), nullable=False, index=True)
    requested_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    status: Mapped[AdditionalInfoRequestStatus] = mapped_column(
        additional_info_request_status_enum,
        nullable=False,
        default=AdditionalInfoRequestStatus.OPEN,
        server_default=AdditionalInfoRequestStatus.OPEN.value,
        index=True,
    )
    public_message: Mapped[str] = mapped_column(Text, nullable=False)
    internal_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    response_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    report: Mapped[Report] = relationship(back_populates="additional_info_requests")
    requested_by_user: Mapped[User | None] = relationship(back_populates="additional_info_requests")

    __table_args__ = (
        Index("ix_additional_info_requests_report_status", "report_id", "status"),
        Index("ix_additional_info_requests_status_due", "status", "due_at"),
    )


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    report_id: Mapped[int | None] = mapped_column(ForeignKey("reports.id", ondelete="CASCADE"), nullable=True, index=True)
    recipient_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    channel: Mapped[str] = mapped_column(String(40), nullable=False, default="IN_APP", server_default="IN_APP", index=True)
    notification_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    subject: Mapped[str | None] = mapped_column(String(200), nullable=True)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[NotificationStatus] = mapped_column(
        notification_status_enum,
        nullable=False,
        default=NotificationStatus.PENDING,
        server_default=NotificationStatus.PENDING.value,
        index=True,
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    report: Mapped[Report | None] = relationship(back_populates="notifications")
    recipient_user: Mapped[User | None] = relationship(back_populates="notifications")

    __table_args__ = (
        Index("ix_notifications_status_scheduled", "status", "scheduled_at"),
        Index("ix_notifications_recipient_status", "recipient_user_id", "status"),
    )


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    entity_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    details: Mapped[str | None] = mapped_column(Text, nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    actor_ip_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    actor_user_agent_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), index=True)

    user: Mapped[User | None] = relationship(back_populates="audit_logs")

    __table_args__ = (
        Index("ix_audit_logs_entity", "entity_type", "entity_id"),
    )
