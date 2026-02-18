"""add program period row results_json

Revision ID: 20260217213000
Revises: 20260217210000
Create Date: 2026-02-17
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260217213000"
down_revision = "20260217210000"
branch_labels = None
depends_on = None


def _has_col(insp, table: str, col: str) -> bool:
    try:
        return any(c["name"] == col for c in insp.get_columns(table))
    except Exception:
        return False


def upgrade() -> None:
    bind = op.get_bind()
    insp = inspect(bind)

    if "program_period_rows" in insp.get_table_names() and not _has_col(insp, "program_period_rows", "results_json"):
        op.add_column(
            "program_period_rows",
            sa.Column("results_json", sa.Text(), nullable=False, server_default="{}"),
        )


def downgrade() -> None:
    # Non-destructive downgrade
    pass
