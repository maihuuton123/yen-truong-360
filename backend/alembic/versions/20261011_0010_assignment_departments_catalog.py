"""add assignment departments catalog

Revision ID: 20261011_0010
Revises: 20261011_0009
Create Date: 2026-10-11 22:05:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20261011_0010"
down_revision: str | None = "20261011_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "departments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("display_order", sa.Integer(), server_default="0", nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_index("ix_departments_is_active", "departments", ["is_active"], unique=False)
    op.create_index("ix_departments_display_order", "departments", ["display_order"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_departments_display_order", table_name="departments")
    op.drop_index("ix_departments_is_active", table_name="departments")
    op.drop_table("departments")
