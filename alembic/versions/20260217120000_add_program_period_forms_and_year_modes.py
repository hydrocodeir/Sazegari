"""add program period forms (quarter/half/year) and year mode lock

Revision ID: 20260217120000
Revises: 20260216120000
Create Date: 2026-02-17
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text


revision = "20260217120000"
down_revision = "20260216120000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = inspect(bind)
    tables = set(insp.get_table_names())

    if "program_period_year_modes" not in tables:
        op.create_table(
            "program_period_year_modes",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("org_id", sa.Integer(), sa.ForeignKey("orgs.id"), nullable=False),
            sa.Column("form_type_id", sa.Integer(), sa.ForeignKey("program_form_types.id"), nullable=False),
            sa.Column("year", sa.Integer(), nullable=False),
            sa.Column("period_type", sa.String(length=16), nullable=False),
            sa.UniqueConstraint("org_id", "form_type_id", "year", name="uq_program_period_year_mode"),
        )
        op.create_index("ix_program_period_year_modes_org_id", "program_period_year_modes", ["org_id"])
        op.create_index("ix_program_period_year_modes_form_type_id", "program_period_year_modes", ["form_type_id"])
        op.create_index("ix_program_period_year_modes_year", "program_period_year_modes", ["year"])
        op.create_index("ix_program_period_year_modes_period_type", "program_period_year_modes", ["period_type"])

    if "program_period_forms" not in tables:
        op.create_table(
            "program_period_forms",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("org_id", sa.Integer(), sa.ForeignKey("orgs.id"), nullable=False),
            sa.Column("form_type_id", sa.Integer(), sa.ForeignKey("program_form_types.id"), nullable=False),
            sa.Column("year", sa.Integer(), nullable=False),
            sa.Column("period_type", sa.String(length=16), nullable=False),
            sa.Column("period_no", sa.Integer(), nullable=False),
            sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.UniqueConstraint(
                "org_id",
                "form_type_id",
                "year",
                "period_type",
                "period_no",
                name="uq_program_period_org_type_year_pt_pn",
            ),
        )
        op.create_index("ix_program_period_forms_org_id", "program_period_forms", ["org_id"])
        op.create_index("ix_program_period_forms_form_type_id", "program_period_forms", ["form_type_id"])
        op.create_index("ix_program_period_forms_year", "program_period_forms", ["year"])
        op.create_index("ix_program_period_forms_period_type", "program_period_forms", ["period_type"])
        op.create_index("ix_program_period_forms_period_no", "program_period_forms", ["period_no"])
        op.create_index("ix_program_period_forms_created_by_id", "program_period_forms", ["created_by_id"])

    if "program_period_rows" not in tables:
        op.create_table(
            "program_period_rows",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("period_form_id", sa.Integer(), sa.ForeignKey("program_period_forms.id"), nullable=False),
            sa.Column("baseline_row_id", sa.Integer(), sa.ForeignKey("program_baseline_rows.id"), nullable=False),
            sa.Column("result_value", sa.Float(), nullable=True),
            sa.Column("actions_text", sa.Text(), nullable=False, server_default=""),
            sa.UniqueConstraint("period_form_id", "baseline_row_id", name="uq_program_period_row_unique"),
        )
        op.create_index("ix_program_period_rows_period_form_id", "program_period_rows", ["period_form_id"])
        op.create_index("ix_program_period_rows_baseline_row_id", "program_period_rows", ["baseline_row_id"])

    # Backward compatibility: if legacy quarterly tables exist, copy them into program_period_* (as quarter)
    # This is best-effort and non-destructive.
    if "program_quarterly_forms" in tables and "program_quarterly_rows" in tables:
        # Copy forms (INSERT IGNORE works on MySQL; for others it may fail silently; guarded by try)
        try:
            bind.execute(
                text(
                    """
                    INSERT IGNORE INTO program_period_forms (org_id, form_type_id, year, period_type, period_no, created_by_id)
                    SELECT org_id, form_type_id, year, 'quarter' AS period_type, quarter AS period_no, created_by_id
                    FROM program_quarterly_forms
                    """
                )
            )
        except Exception:
            pass

        # Copy rows (map via (org, type, year, quarter))
        try:
            bind.execute(
                text(
                    """
                    INSERT IGNORE INTO program_period_rows (period_form_id, baseline_row_id, result_value, actions_text)
                    SELECT pf.id, qr.baseline_row_id, qr.result_value, COALESCE(qr.actions_text, '')
                    FROM program_quarterly_rows qr
                    JOIN program_quarterly_forms qf ON qf.id = qr.quarterly_form_id
                    JOIN program_period_forms pf
                      ON pf.org_id = qf.org_id
                     AND pf.form_type_id = qf.form_type_id
                     AND pf.year = qf.year
                     AND pf.period_type = 'quarter'
                     AND pf.period_no = qf.quarter
                    """
                )
            )
        except Exception:
            pass

        # Seed year mode lock for years that already have quarterly data
        try:
            bind.execute(
                text(
                    """
                    INSERT IGNORE INTO program_period_year_modes (org_id, form_type_id, year, period_type)
                    SELECT DISTINCT org_id, form_type_id, year, 'quarter'
                    FROM program_quarterly_forms
                    """
                )
            )
        except Exception:
            pass


def downgrade() -> None:
    # Intentionally no destructive downgrade
    pass
