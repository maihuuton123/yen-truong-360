"""add v23 anti spam source blocks

Revision ID: 20261007_0004
Revises: 20261007_0003
Create Date: 2026-10-07 22:40:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20261007_0004"
down_revision: str | None = "20261007_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "report_source_blocks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source_type", sa.String(length=40), nullable=False),
        sa.Column("source_hash", sa.String(length=128), nullable=False),
        sa.Column("reason", sa.String(length=500), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lifted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("lifted_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["lifted_by"], ["users.id"], ondelete="SET NULL"),
        sa.CheckConstraint("source_type IN ('IP', 'FINGERPRINT')", name="ck_report_source_blocks_source_type"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_report_source_blocks_source_type", "report_source_blocks", ["source_type"], unique=False)
    op.create_index("ix_report_source_blocks_source_hash", "report_source_blocks", ["source_hash"], unique=False)
    op.create_index("ix_report_source_blocks_is_active", "report_source_blocks", ["is_active"], unique=False)
    op.create_index("ix_report_source_blocks_expires_at", "report_source_blocks", ["expires_at"], unique=False)
    op.create_index("ix_report_source_blocks_created_by", "report_source_blocks", ["created_by"], unique=False)
    op.create_index("ix_report_source_blocks_lifted_by", "report_source_blocks", ["lifted_by"], unique=False)
    op.create_index("ix_report_source_blocks_created_at", "report_source_blocks", ["created_at"], unique=False)
    op.create_index(
        "ix_report_source_blocks_source_active",
        "report_source_blocks",
        ["source_type", "source_hash", "is_active"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_report_source_blocks_source_active", table_name="report_source_blocks")
    op.drop_index("ix_report_source_blocks_created_at", table_name="report_source_blocks")
    op.drop_index("ix_report_source_blocks_lifted_by", table_name="report_source_blocks")
    op.drop_index("ix_report_source_blocks_created_by", table_name="report_source_blocks")
    op.drop_index("ix_report_source_blocks_expires_at", table_name="report_source_blocks")
    op.drop_index("ix_report_source_blocks_is_active", table_name="report_source_blocks")
    op.drop_index("ix_report_source_blocks_source_hash", table_name="report_source_blocks")
    op.drop_index("ix_report_source_blocks_source_type", table_name="report_source_blocks")
    op.drop_table("report_source_blocks")
