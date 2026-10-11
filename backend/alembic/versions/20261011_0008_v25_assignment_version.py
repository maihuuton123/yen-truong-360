"""add assignment version for conflict checks

Revision ID: 20261011_0008
Revises: 20261011_0007
Create Date: 2026-10-11 17:10:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20261011_0008"
down_revision: str | None = "20261011_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "reports",
        sa.Column("assignment_version", sa.Integer(), server_default="0", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("reports", "assignment_version")
