"""store attachment bytes as render-safe fallback

Revision ID: 20261011_0009
Revises: 20261011_0008
Create Date: 2026-10-11 21:30:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20261011_0009"
down_revision: str | None = "20261011_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("attachments", sa.Column("file_data", sa.LargeBinary(), nullable=True))


def downgrade() -> None:
    op.drop_column("attachments", "file_data")
