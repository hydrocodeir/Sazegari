"""add county scope to program period tables

Revision ID: 20260217193000
Revises: 20260217120000
Create Date: 2026-02-17

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect



# revision identifiers, used by Alembic.
revision = "20260217193000"
down_revision = "20260217120000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = inspect(bind)

    def has_index(table: str, name: str) -> bool:
        try:
            return any(i.get("name") == name for i in insp.get_indexes(table))
        except Exception:
            return False

    # ---- program_period_forms ----
    cols = {c["name"] for c in insp.get_columns("program_period_forms")}
    target_uq = ["org_id", "county_id", "form_type_id", "year", "period_type", "period_no"]

    with op.batch_alter_table("program_period_forms") as b:
        if "county_id" not in cols:
            b.add_column(sa.Column("county_id", sa.Integer(), nullable=False, server_default="0"))

        # best-effort: drop old uq then create new uq (skip errors)
        try:
            b.drop_constraint("uq_program_period_org_type_year_pt_pn", type_="unique")
        except Exception:
            pass
        try:
            b.create_unique_constraint("uq_program_period_org_type_year_pt_pn", target_uq)
        except Exception:
            pass

        if not has_index("program_period_forms", "ix_program_period_forms_county_id"):
            try:
                b.create_index("ix_program_period_forms_county_id", ["county_id"])
            except Exception:
                pass

    # ---- program_period_year_modes ----
    cols = {c["name"] for c in insp.get_columns("program_period_year_modes")}
    target_uq = ["org_id", "county_id", "form_type_id", "year"]

    with op.batch_alter_table("program_period_year_modes") as b:
        if "county_id" not in cols:
            b.add_column(sa.Column("county_id", sa.Integer(), nullable=False, server_default="0"))

        try:
            b.drop_constraint("uq_program_period_year_mode", type_="unique")
        except Exception:
            pass
        try:
            b.create_unique_constraint("uq_program_period_year_mode", target_uq)
        except Exception:
            pass

        if not has_index("program_period_year_modes", "ix_program_period_year_modes_county_id"):
            try:
                b.create_index("ix_program_period_year_modes_county_id", ["county_id"])
            except Exception:
                pass


def downgrade() -> None:
    with op.batch_alter_table("program_period_year_modes") as b:
        b.drop_index("ix_program_period_year_modes_county_id")
        b.drop_constraint("uq_program_period_year_mode", type_="unique")
        b.create_unique_constraint("uq_program_period_year_mode", ["org_id", "form_type_id", "year"])
        b.drop_column("county_id")

    with op.batch_alter_table("program_period_forms") as b:
        b.drop_index("ix_program_period_forms_county_id")
        b.drop_constraint("uq_program_period_org_type_year_pt_pn", type_="unique")
        b.create_unique_constraint(
            "uq_program_period_org_type_year_pt_pn",
            ["org_id", "form_type_id", "year", "period_type", "period_no"],
        )
        b.drop_column("county_id")
