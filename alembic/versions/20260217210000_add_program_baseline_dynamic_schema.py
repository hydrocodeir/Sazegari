"""add program baseline dynamic schema columns

Revision ID: 20260217210000
Revises: 20260217193000
Create Date: 2026-02-17
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260217210000"
down_revision = "20260217193000"
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

    if "program_form_types" in insp.get_table_names() and not _has_col(insp, "program_form_types", "baseline_schema_json"):
        op.add_column("program_form_types", sa.Column("baseline_schema_json", sa.Text(), nullable=False, server_default=""))

    if "program_baseline_rows" in insp.get_table_names():
        if not _has_col(insp, "program_baseline_rows", "data_json"):
            op.add_column("program_baseline_rows", sa.Column("data_json", sa.Text(), nullable=False, server_default="{}"))
        if not _has_col(insp, "program_baseline_rows", "targets_json"):
            op.add_column("program_baseline_rows", sa.Column("targets_json", sa.Text(), nullable=False, server_default="{}"))


def downgrade() -> None:
    # Non-destructive downgrade
    pass
