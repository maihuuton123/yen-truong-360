"""add secure additional information response tokens

Revision ID: 20261014_0011
Revises: 20261011_0010
Create Date: 2026-10-14 09:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20261014_0011"
down_revision: str | None = "20261011_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("additional_info_requests", sa.Column("response_token_hash", sa.String(length=64), nullable=True))
    op.add_column(
        "additional_info_requests",
        sa.Column("response_token_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_additional_info_requests_response_token_hash",
        "additional_info_requests",
        ["response_token_hash"],
        unique=True,
    )
    op.create_index(
        "ix_additional_info_requests_response_token_expires_at",
        "additional_info_requests",
        ["response_token_expires_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_additional_info_requests_response_token_expires_at", table_name="additional_info_requests")
    op.drop_index("ix_additional_info_requests_response_token_hash", table_name="additional_info_requests")
    op.drop_column("additional_info_requests", "response_token_expires_at")
    op.drop_column("additional_info_requests", "response_token_hash")
