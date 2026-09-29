"""create core tables

Revision ID: 20260929_0001
Revises:
Create Date: 2026-09-29 00:01:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260929_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


report_status_values = (
    "NEW",
    "RECEIVED",
    "COORDINATING",
    "RESOLVED",
    "OUT_OF_SCOPE",
)


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("username", sa.String(length=80), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("full_name", sa.String(length=150), nullable=False),
        sa.Column("role", sa.String(length=50), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("username"),
    )
    op.create_index("ix_users_username", "users", ["username"], unique=False)
    op.create_index("ix_users_role", "users", ["role"], unique=False)

    op.create_table(
        "categories",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("icon", sa.String(length=80), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("display_order", sa.Integer(), server_default="0", nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_index("ix_categories_is_active", "categories", ["is_active"], unique=False)
    op.create_index("ix_categories_display_order", "categories", ["display_order"], unique=False)

    op.create_table(
        "areas",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("display_order", sa.Integer(), server_default="0", nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_index("ix_areas_is_active", "areas", ["is_active"], unique=False)
    op.create_index("ix_areas_display_order", "areas", ["display_order"], unique=False)

    op.create_table(
        "reports",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tracking_code", sa.String(length=40), nullable=False),
        sa.Column("category_id", sa.Integer(), nullable=False),
        sa.Column("area_id", sa.Integer(), nullable=True),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), server_default="NEW", nullable=False),
        sa.Column("public_response", sa.Text(), nullable=True),
        sa.Column("internal_note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["area_id"], ["areas.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["category_id"], ["categories.id"], ondelete="RESTRICT"),
        sa.CheckConstraint(f"status IN {report_status_values}", name="ck_reports_status"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tracking_code"),
    )
    op.create_index("ix_reports_tracking_code", "reports", ["tracking_code"], unique=False)
    op.create_index("ix_reports_category_id", "reports", ["category_id"], unique=False)
    op.create_index("ix_reports_area_id", "reports", ["area_id"], unique=False)
    op.create_index("ix_reports_status", "reports", ["status"], unique=False)
    op.create_index("ix_reports_created_at", "reports", ["created_at"], unique=False)
    op.create_index("ix_reports_status_created_at", "reports", ["status", "created_at"], unique=False)
    op.create_index("ix_reports_category_status", "reports", ["category_id", "status"], unique=False)

    op.create_table(
        "attachments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("report_id", sa.Integer(), nullable=False),
        sa.Column("stored_filename", sa.String(length=255), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("mime_type", sa.String(length=120), nullable=False),
        sa.Column("file_size", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["report_id"], ["reports.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_attachments_report_id", "attachments", ["report_id"], unique=False)

    op.create_table(
        "status_history",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("report_id", sa.Integer(), nullable=False),
        sa.Column("old_status", sa.String(length=32), nullable=True),
        sa.Column("new_status", sa.String(length=32), nullable=False),
        sa.Column("public_note", sa.Text(), nullable=True),
        sa.Column("internal_note", sa.Text(), nullable=True),
        sa.Column("changed_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["changed_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["report_id"], ["reports.id"], ondelete="CASCADE"),
        sa.CheckConstraint(
            f"old_status IS NULL OR old_status IN {report_status_values}",
            name="ck_status_history_old_status",
        ),
        sa.CheckConstraint(f"new_status IN {report_status_values}", name="ck_status_history_new_status"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_status_history_report_id", "status_history", ["report_id"], unique=False)
    op.create_index("ix_status_history_new_status", "status_history", ["new_status"], unique=False)
    op.create_index("ix_status_history_changed_by", "status_history", ["changed_by"], unique=False)
    op.create_index("ix_status_history_created_at", "status_history", ["created_at"], unique=False)
    op.create_index(
        "ix_status_history_report_created_at",
        "status_history",
        ["report_id", "created_at"],
        unique=False,
    )

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("action", sa.String(length=120), nullable=False),
        sa.Column("entity_type", sa.String(length=80), nullable=False),
        sa.Column("entity_id", sa.Integer(), nullable=True),
        sa.Column("details", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_audit_logs_user_id", "audit_logs", ["user_id"], unique=False)
    op.create_index("ix_audit_logs_action", "audit_logs", ["action"], unique=False)
    op.create_index("ix_audit_logs_entity_type", "audit_logs", ["entity_type"], unique=False)
    op.create_index("ix_audit_logs_entity_id", "audit_logs", ["entity_id"], unique=False)
    op.create_index("ix_audit_logs_created_at", "audit_logs", ["created_at"], unique=False)
    op.create_index("ix_audit_logs_entity", "audit_logs", ["entity_type", "entity_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_audit_logs_entity", table_name="audit_logs")
    op.drop_index("ix_audit_logs_created_at", table_name="audit_logs")
    op.drop_index("ix_audit_logs_entity_id", table_name="audit_logs")
    op.drop_index("ix_audit_logs_entity_type", table_name="audit_logs")
    op.drop_index("ix_audit_logs_action", table_name="audit_logs")
    op.drop_index("ix_audit_logs_user_id", table_name="audit_logs")
    op.drop_table("audit_logs")

    op.drop_index("ix_status_history_report_created_at", table_name="status_history")
    op.drop_index("ix_status_history_created_at", table_name="status_history")
    op.drop_index("ix_status_history_changed_by", table_name="status_history")
    op.drop_index("ix_status_history_new_status", table_name="status_history")
    op.drop_index("ix_status_history_report_id", table_name="status_history")
    op.drop_table("status_history")

    op.drop_index("ix_attachments_report_id", table_name="attachments")
    op.drop_table("attachments")

    op.drop_index("ix_reports_category_status", table_name="reports")
    op.drop_index("ix_reports_status_created_at", table_name="reports")
    op.drop_index("ix_reports_created_at", table_name="reports")
    op.drop_index("ix_reports_status", table_name="reports")
    op.drop_index("ix_reports_area_id", table_name="reports")
    op.drop_index("ix_reports_category_id", table_name="reports")
    op.drop_index("ix_reports_tracking_code", table_name="reports")
    op.drop_table("reports")

    op.drop_index("ix_areas_display_order", table_name="areas")
    op.drop_index("ix_areas_is_active", table_name="areas")
    op.drop_table("areas")

    op.drop_index("ix_categories_display_order", table_name="categories")
    op.drop_index("ix_categories_is_active", table_name="categories")
    op.drop_table("categories")

    op.drop_index("ix_users_role", table_name="users")
    op.drop_index("ix_users_username", table_name="users")
    op.drop_table("users")
