"""enforce v2 report foreign keys on sqlite

Revision ID: 20261007_0003
Revises: 20261007_0002
Create Date: 2026-10-07 00:03:00
"""

from collections.abc import Sequence

from alembic import op


revision: str = "20261007_0003"
down_revision: str | None = "20261007_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if op.get_bind().dialect.name != "sqlite":
        return

    with op.batch_alter_table("reports", recreate="always") as batch_op:
        batch_op.create_foreign_key(
            "fk_reports_assigned_to_users",
            "users",
            ["assigned_to"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_foreign_key(
            "fk_reports_duplicate_of_report_id_reports",
            "reports",
            ["duplicate_of_report_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    if op.get_bind().dialect.name != "sqlite":
        return

    with op.batch_alter_table("reports", recreate="always") as batch_op:
        batch_op.drop_constraint("fk_reports_duplicate_of_report_id_reports", type_="foreignkey")
        batch_op.drop_constraint("fk_reports_assigned_to_users", type_="foreignkey")
