"""add assignment department fields

Revision ID: 20261011_0007
Revises: 20261011_0006
Create Date: 2026-10-11 16:20:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20261011_0007"
down_revision: str | None = "20261011_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("reports", sa.Column("assigned_department", sa.String(length=160), nullable=True))
    op.create_index("ix_reports_assigned_department", "reports", ["assigned_department"], unique=False)
    op.add_column("report_assignment_history", sa.Column("old_assigned_department", sa.String(length=160), nullable=True))
    op.add_column("report_assignment_history", sa.Column("new_assigned_department", sa.String(length=160), nullable=True))


def downgrade() -> None:
    op.drop_column("report_assignment_history", "new_assigned_department")
    op.drop_column("report_assignment_history", "old_assigned_department")
    op.drop_index("ix_reports_assigned_department", table_name="reports")
    op.drop_column("reports", "assigned_department")
