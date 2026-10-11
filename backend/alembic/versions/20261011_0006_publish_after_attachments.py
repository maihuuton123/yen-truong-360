"""publish after-processing attachments

Revision ID: 20261011_0006
Revises: 20261007_0005
Create Date: 2026-10-11 09:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20261011_0006"
down_revision: str | None = "20261007_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE attachments SET is_public = :is_public WHERE attachment_type = :attachment_type"
        ).bindparams(is_public=True, attachment_type="AFTER")
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE attachments SET is_public = :is_public WHERE attachment_type = :attachment_type"
        ).bindparams(is_public=False, attachment_type="AFTER")
    )
