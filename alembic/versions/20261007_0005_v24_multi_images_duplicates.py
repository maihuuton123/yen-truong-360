"""add v24 multi image metadata and duplicate links

Revision ID: 20261007_0005
Revises: 20261007_0004
Create Date: 2026-10-07 23:20:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20261007_0005"
down_revision: str | None = "20261007_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


attachment_type_values = ("INITIAL", "BEFORE", "AFTER", "OTHER")
duplicate_link_status_values = ("SUGGESTED", "LINKED", "DISMISSED")


def upgrade() -> None:
    op.add_column(
        "attachments",
        sa.Column("attachment_type", sa.String(length=32), server_default="INITIAL", nullable=False),
    )
    op.add_column(
        "attachments",
        sa.Column("is_public", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    if op.get_bind().dialect.name != "sqlite":
        op.create_check_constraint(
            "ck_attachments_attachment_type",
            "attachments",
            f"attachment_type IN {attachment_type_values}",
        )
    op.create_index("ix_attachments_attachment_type", "attachments", ["attachment_type"], unique=False)
    op.create_index("ix_attachments_is_public", "attachments", ["is_public"], unique=False)
    op.create_index("ix_attachments_report_type", "attachments", ["report_id", "attachment_type"], unique=False)

    op.create_table(
        "report_duplicate_links",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("report_id", sa.Integer(), nullable=False),
        sa.Column("related_report_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), server_default="SUGGESTED", nullable=False),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("reason", sa.String(length=500), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(f"status IN {duplicate_link_status_values}", name="ck_report_duplicate_links_status"),
        sa.CheckConstraint("report_id <> related_report_id", name="ck_report_duplicate_links_not_self"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["related_report_id"], ["reports.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["report_id"], ["reports.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_report_duplicate_links_report_id", "report_duplicate_links", ["report_id"], unique=False)
    op.create_index(
        "ix_report_duplicate_links_related_report_id",
        "report_duplicate_links",
        ["related_report_id"],
        unique=False,
    )
    op.create_index("ix_report_duplicate_links_status", "report_duplicate_links", ["status"], unique=False)
    op.create_index("ix_report_duplicate_links_created_by", "report_duplicate_links", ["created_by"], unique=False)
    op.create_index("ix_report_duplicate_links_created_at", "report_duplicate_links", ["created_at"], unique=False)
    op.create_index(
        "ix_report_duplicate_links_pair",
        "report_duplicate_links",
        ["report_id", "related_report_id"],
        unique=True,
    )
    op.create_index(
        "ix_report_duplicate_links_status_score",
        "report_duplicate_links",
        ["status", "score"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_report_duplicate_links_status_score", table_name="report_duplicate_links")
    op.drop_index("ix_report_duplicate_links_pair", table_name="report_duplicate_links")
    op.drop_index("ix_report_duplicate_links_created_at", table_name="report_duplicate_links")
    op.drop_index("ix_report_duplicate_links_created_by", table_name="report_duplicate_links")
    op.drop_index("ix_report_duplicate_links_status", table_name="report_duplicate_links")
    op.drop_index("ix_report_duplicate_links_related_report_id", table_name="report_duplicate_links")
    op.drop_index("ix_report_duplicate_links_report_id", table_name="report_duplicate_links")
    op.drop_table("report_duplicate_links")

    op.drop_index("ix_attachments_report_type", table_name="attachments")
    op.drop_index("ix_attachments_is_public", table_name="attachments")
    op.drop_index("ix_attachments_attachment_type", table_name="attachments")
    if op.get_bind().dialect.name != "sqlite":
        op.drop_constraint("ck_attachments_attachment_type", "attachments", type_="check")
    op.drop_column("attachments", "is_public")
    op.drop_column("attachments", "attachment_type")
