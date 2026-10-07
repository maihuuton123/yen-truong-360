"""add v2 case management schema

Revision ID: 20261007_0002
Revises: 20260929_0001
Create Date: 2026-10-07 00:02:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20261007_0002"
down_revision: str | None = "20260929_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


priority_values = ("LOW", "NORMAL", "HIGH", "URGENT")
additional_info_request_status_values = ("OPEN", "RESPONDED", "CLOSED", "CANCELLED")
notification_status_values = ("PENDING", "SENT", "FAILED", "CANCELLED")
notification_channel_values = ("IN_APP", "EMAIL", "WEBHOOK")


def upgrade() -> None:
    is_sqlite = op.get_bind().dialect.name == "sqlite"

    op.add_column("reports", sa.Column("priority", sa.String(length=32), server_default="NORMAL", nullable=False))
    op.add_column("reports", sa.Column("assigned_to", sa.Integer(), nullable=True))
    op.add_column("reports", sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("reports", sa.Column("deadline_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("reports", sa.Column("location_text", sa.String(length=500), nullable=True))
    op.add_column("reports", sa.Column("location_latitude", sa.Float(), nullable=True))
    op.add_column("reports", sa.Column("location_longitude", sa.Float(), nullable=True))
    op.add_column("reports", sa.Column("location_accuracy_meters", sa.Integer(), nullable=True))
    op.add_column("reports", sa.Column("is_duplicate", sa.Boolean(), server_default=sa.false(), nullable=False))
    op.add_column("reports", sa.Column("duplicate_of_report_id", sa.Integer(), nullable=True))
    op.add_column("reports", sa.Column("is_spam", sa.Boolean(), server_default=sa.false(), nullable=False))
    op.add_column("reports", sa.Column("spam_score", sa.Float(), nullable=True))
    op.add_column("reports", sa.Column("spam_reason", sa.String(length=500), nullable=True))
    op.add_column("reports", sa.Column("moderation_status", sa.String(length=40), server_default="UNREVIEWED", nullable=False))
    op.add_column("reports", sa.Column("reporter_ip_hash", sa.String(length=128), nullable=True))
    op.add_column("reports", sa.Column("reporter_user_agent_hash", sa.String(length=128), nullable=True))
    op.add_column("reports", sa.Column("request_fingerprint_hash", sa.String(length=128), nullable=True))
    op.add_column("reports", sa.Column("submission_source", sa.String(length=60), server_default="public_form", nullable=False))
    op.add_column("reports", sa.Column("client_submitted_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("reports", sa.Column("technical_metadata", sa.Text(), nullable=True))

    if not is_sqlite:
        op.create_foreign_key("fk_reports_assigned_to_users", "reports", "users", ["assigned_to"], ["id"], ondelete="SET NULL")
        op.create_foreign_key(
            "fk_reports_duplicate_of_report_id_reports",
            "reports",
            "reports",
            ["duplicate_of_report_id"],
            ["id"],
            ondelete="SET NULL",
        )

    op.create_index("ix_reports_priority", "reports", ["priority"], unique=False)
    op.create_index("ix_reports_assigned_to", "reports", ["assigned_to"], unique=False)
    op.create_index("ix_reports_deadline_at", "reports", ["deadline_at"], unique=False)
    op.create_index("ix_reports_is_duplicate", "reports", ["is_duplicate"], unique=False)
    op.create_index("ix_reports_duplicate_of_report_id", "reports", ["duplicate_of_report_id"], unique=False)
    op.create_index("ix_reports_is_spam", "reports", ["is_spam"], unique=False)
    op.create_index("ix_reports_moderation_status", "reports", ["moderation_status"], unique=False)
    op.create_index("ix_reports_reporter_ip_hash", "reports", ["reporter_ip_hash"], unique=False)
    op.create_index("ix_reports_request_fingerprint_hash", "reports", ["request_fingerprint_hash"], unique=False)
    op.create_index("ix_reports_submission_source", "reports", ["submission_source"], unique=False)
    op.create_index("ix_reports_priority_deadline", "reports", ["priority", "deadline_at"], unique=False)
    op.create_index("ix_reports_assigned_status", "reports", ["assigned_to", "status"], unique=False)
    op.create_index("ix_reports_spam_duplicate", "reports", ["is_spam", "is_duplicate"], unique=False)

    op.create_table(
        "report_assignment_history",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("report_id", sa.Integer(), nullable=False),
        sa.Column("old_assigned_to", sa.Integer(), nullable=True),
        sa.Column("new_assigned_to", sa.Integer(), nullable=True),
        sa.Column("old_priority", sa.String(length=32), nullable=True),
        sa.Column("new_priority", sa.String(length=32), nullable=True),
        sa.Column("old_deadline_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("new_deadline_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("changed_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["changed_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["new_assigned_to"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["old_assigned_to"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["report_id"], ["reports.id"], ondelete="CASCADE"),
        sa.CheckConstraint(
            f"old_priority IS NULL OR old_priority IN {priority_values}",
            name="ck_report_assignment_history_old_priority",
        ),
        sa.CheckConstraint(
            f"new_priority IS NULL OR new_priority IN {priority_values}",
            name="ck_report_assignment_history_new_priority",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_report_assignment_history_report_id", "report_assignment_history", ["report_id"], unique=False)
    op.create_index("ix_report_assignment_history_old_assigned_to", "report_assignment_history", ["old_assigned_to"], unique=False)
    op.create_index("ix_report_assignment_history_new_assigned_to", "report_assignment_history", ["new_assigned_to"], unique=False)
    op.create_index("ix_report_assignment_history_changed_by", "report_assignment_history", ["changed_by"], unique=False)
    op.create_index("ix_report_assignment_history_created_at", "report_assignment_history", ["created_at"], unique=False)
    op.create_index(
        "ix_report_assignment_history_report_created_at",
        "report_assignment_history",
        ["report_id", "created_at"],
        unique=False,
    )

    op.create_table(
        "report_internal_notes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("report_id", sa.Integer(), nullable=False),
        sa.Column("author_user_id", sa.Integer(), nullable=True),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("is_deleted", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["author_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["report_id"], ["reports.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_report_internal_notes_report_id", "report_internal_notes", ["report_id"], unique=False)
    op.create_index("ix_report_internal_notes_author_user_id", "report_internal_notes", ["author_user_id"], unique=False)
    op.create_index("ix_report_internal_notes_is_deleted", "report_internal_notes", ["is_deleted"], unique=False)
    op.create_index("ix_report_internal_notes_created_at", "report_internal_notes", ["created_at"], unique=False)
    op.create_index(
        "ix_report_internal_notes_report_created_at",
        "report_internal_notes",
        ["report_id", "created_at"],
        unique=False,
    )

    op.create_table(
        "additional_info_requests",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("report_id", sa.Integer(), nullable=False),
        sa.Column("requested_by", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=32), server_default="OPEN", nullable=False),
        sa.Column("public_message", sa.Text(), nullable=False),
        sa.Column("internal_note", sa.Text(), nullable=True),
        sa.Column("response_text", sa.Text(), nullable=True),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("responded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["report_id"], ["reports.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["requested_by"], ["users.id"], ondelete="SET NULL"),
        sa.CheckConstraint(f"status IN {additional_info_request_status_values}", name="ck_additional_info_requests_status"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_additional_info_requests_report_id", "additional_info_requests", ["report_id"], unique=False)
    op.create_index("ix_additional_info_requests_requested_by", "additional_info_requests", ["requested_by"], unique=False)
    op.create_index("ix_additional_info_requests_status", "additional_info_requests", ["status"], unique=False)
    op.create_index("ix_additional_info_requests_due_at", "additional_info_requests", ["due_at"], unique=False)
    op.create_index("ix_additional_info_requests_created_at", "additional_info_requests", ["created_at"], unique=False)
    op.create_index(
        "ix_additional_info_requests_report_status",
        "additional_info_requests",
        ["report_id", "status"],
        unique=False,
    )
    op.create_index(
        "ix_additional_info_requests_status_due",
        "additional_info_requests",
        ["status", "due_at"],
        unique=False,
    )

    op.create_table(
        "notifications",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("report_id", sa.Integer(), nullable=True),
        sa.Column("recipient_user_id", sa.Integer(), nullable=True),
        sa.Column("channel", sa.String(length=40), server_default="IN_APP", nullable=False),
        sa.Column("notification_type", sa.String(length=80), nullable=False),
        sa.Column("subject", sa.String(length=200), nullable=True),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), server_default="PENDING", nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["recipient_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["report_id"], ["reports.id"], ondelete="CASCADE"),
        sa.CheckConstraint(f"channel IN {notification_channel_values}", name="ck_notifications_channel"),
        sa.CheckConstraint(f"status IN {notification_status_values}", name="ck_notifications_status"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_notifications_report_id", "notifications", ["report_id"], unique=False)
    op.create_index("ix_notifications_recipient_user_id", "notifications", ["recipient_user_id"], unique=False)
    op.create_index("ix_notifications_channel", "notifications", ["channel"], unique=False)
    op.create_index("ix_notifications_notification_type", "notifications", ["notification_type"], unique=False)
    op.create_index("ix_notifications_status", "notifications", ["status"], unique=False)
    op.create_index("ix_notifications_scheduled_at", "notifications", ["scheduled_at"], unique=False)
    op.create_index("ix_notifications_created_at", "notifications", ["created_at"], unique=False)
    op.create_index("ix_notifications_status_scheduled", "notifications", ["status", "scheduled_at"], unique=False)
    op.create_index("ix_notifications_recipient_status", "notifications", ["recipient_user_id", "status"], unique=False)

    op.add_column("audit_logs", sa.Column("request_id", sa.String(length=80), nullable=True))
    op.add_column("audit_logs", sa.Column("actor_ip_hash", sa.String(length=128), nullable=True))
    op.add_column("audit_logs", sa.Column("actor_user_agent_hash", sa.String(length=128), nullable=True))
    op.create_index("ix_audit_logs_request_id", "audit_logs", ["request_id"], unique=False)


def downgrade() -> None:
    is_sqlite = op.get_bind().dialect.name == "sqlite"

    op.drop_index("ix_audit_logs_request_id", table_name="audit_logs")
    op.drop_column("audit_logs", "actor_user_agent_hash")
    op.drop_column("audit_logs", "actor_ip_hash")
    op.drop_column("audit_logs", "request_id")

    op.drop_index("ix_notifications_recipient_status", table_name="notifications")
    op.drop_index("ix_notifications_status_scheduled", table_name="notifications")
    op.drop_index("ix_notifications_created_at", table_name="notifications")
    op.drop_index("ix_notifications_scheduled_at", table_name="notifications")
    op.drop_index("ix_notifications_status", table_name="notifications")
    op.drop_index("ix_notifications_notification_type", table_name="notifications")
    op.drop_index("ix_notifications_channel", table_name="notifications")
    op.drop_index("ix_notifications_recipient_user_id", table_name="notifications")
    op.drop_index("ix_notifications_report_id", table_name="notifications")
    op.drop_table("notifications")

    op.drop_index("ix_additional_info_requests_status_due", table_name="additional_info_requests")
    op.drop_index("ix_additional_info_requests_report_status", table_name="additional_info_requests")
    op.drop_index("ix_additional_info_requests_created_at", table_name="additional_info_requests")
    op.drop_index("ix_additional_info_requests_due_at", table_name="additional_info_requests")
    op.drop_index("ix_additional_info_requests_status", table_name="additional_info_requests")
    op.drop_index("ix_additional_info_requests_requested_by", table_name="additional_info_requests")
    op.drop_index("ix_additional_info_requests_report_id", table_name="additional_info_requests")
    op.drop_table("additional_info_requests")

    op.drop_index("ix_report_internal_notes_report_created_at", table_name="report_internal_notes")
    op.drop_index("ix_report_internal_notes_created_at", table_name="report_internal_notes")
    op.drop_index("ix_report_internal_notes_is_deleted", table_name="report_internal_notes")
    op.drop_index("ix_report_internal_notes_author_user_id", table_name="report_internal_notes")
    op.drop_index("ix_report_internal_notes_report_id", table_name="report_internal_notes")
    op.drop_table("report_internal_notes")

    op.drop_index("ix_report_assignment_history_report_created_at", table_name="report_assignment_history")
    op.drop_index("ix_report_assignment_history_created_at", table_name="report_assignment_history")
    op.drop_index("ix_report_assignment_history_changed_by", table_name="report_assignment_history")
    op.drop_index("ix_report_assignment_history_new_assigned_to", table_name="report_assignment_history")
    op.drop_index("ix_report_assignment_history_old_assigned_to", table_name="report_assignment_history")
    op.drop_index("ix_report_assignment_history_report_id", table_name="report_assignment_history")
    op.drop_table("report_assignment_history")

    op.drop_index("ix_reports_spam_duplicate", table_name="reports")
    op.drop_index("ix_reports_assigned_status", table_name="reports")
    op.drop_index("ix_reports_priority_deadline", table_name="reports")
    op.drop_index("ix_reports_submission_source", table_name="reports")
    op.drop_index("ix_reports_request_fingerprint_hash", table_name="reports")
    op.drop_index("ix_reports_reporter_ip_hash", table_name="reports")
    op.drop_index("ix_reports_moderation_status", table_name="reports")
    op.drop_index("ix_reports_is_spam", table_name="reports")
    op.drop_index("ix_reports_duplicate_of_report_id", table_name="reports")
    op.drop_index("ix_reports_is_duplicate", table_name="reports")
    op.drop_index("ix_reports_deadline_at", table_name="reports")
    op.drop_index("ix_reports_assigned_to", table_name="reports")
    op.drop_index("ix_reports_priority", table_name="reports")
    if not is_sqlite:
        op.drop_constraint("fk_reports_duplicate_of_report_id_reports", "reports", type_="foreignkey")
        op.drop_constraint("fk_reports_assigned_to_users", "reports", type_="foreignkey")
    op.drop_column("reports", "technical_metadata")
    op.drop_column("reports", "client_submitted_at")
    op.drop_column("reports", "submission_source")
    op.drop_column("reports", "request_fingerprint_hash")
    op.drop_column("reports", "reporter_user_agent_hash")
    op.drop_column("reports", "reporter_ip_hash")
    op.drop_column("reports", "moderation_status")
    op.drop_column("reports", "spam_reason")
    op.drop_column("reports", "spam_score")
    op.drop_column("reports", "is_spam")
    op.drop_column("reports", "duplicate_of_report_id")
    op.drop_column("reports", "is_duplicate")
    op.drop_column("reports", "location_accuracy_meters")
    op.drop_column("reports", "location_longitude")
    op.drop_column("reports", "location_latitude")
    op.drop_column("reports", "location_text")
    op.drop_column("reports", "deadline_at")
    op.drop_column("reports", "assigned_at")
    op.drop_column("reports", "assigned_to")
    op.drop_column("reports", "priority")
