"""add program baseline/quarterly tracking tables

Revision ID: 20260216120000
Revises: 20260213120000
Create Date: 2026-02-16
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260216120000"
down_revision = "20260213120000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = inspect(bind)
    tables = set(insp.get_table_names())

    if "program_form_types" not in tables:
        op.create_table(
            "program_form_types",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("org_id", sa.Integer(), sa.ForeignKey("orgs.id"), nullable=False),
            sa.Column("title", sa.String(length=200), nullable=False),
            sa.Column("intro_text", sa.Text(), nullable=False, server_default="مقدمه: (متن ثابت/قابل‌ویرایش توسط کارشناس استان)"),
            sa.Column("conclusion_text", sa.Text(), nullable=False, server_default="نتیجه‌گیری: (متن ثابت/قابل‌ویرایش توسط کارشناس استان)"),
            sa.UniqueConstraint("org_id", "title", name="uq_program_form_types_org_title"),
        )
        op.create_index("ix_program_form_types_org_id", "program_form_types", ["org_id"])
        op.create_index("ix_program_form_types_title", "program_form_types", ["title"])

    if "program_baselines" not in tables:
        op.create_table(
            "program_baselines",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("org_id", sa.Integer(), sa.ForeignKey("orgs.id"), nullable=False),
            sa.Column("form_type_id", sa.Integer(), sa.ForeignKey("program_form_types.id"), nullable=False),
            sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.UniqueConstraint("org_id", "form_type_id", name="uq_program_baselines_org_type"),
        )
        op.create_index("ix_program_baselines_org_id", "program_baselines", ["org_id"])
        op.create_index("ix_program_baselines_form_type_id", "program_baselines", ["form_type_id"])
        op.create_index("ix_program_baselines_created_by_id", "program_baselines", ["created_by_id"])

    if "program_baseline_rows" not in tables:
        op.create_table(
            "program_baseline_rows",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("baseline_id", sa.Integer(), sa.ForeignKey("program_baselines.id"), nullable=False),
            sa.Column("row_no", sa.Integer(), nullable=False),
            sa.Column("title", sa.String(length=400), nullable=False),
            sa.Column("unit", sa.String(length=80), nullable=False, server_default=""),
            sa.Column("start_year", sa.Integer(), nullable=False),
            sa.Column("end_year", sa.Integer(), nullable=False),
            sa.Column("target_value", sa.Float(), nullable=False),
            sa.Column("notes", sa.Text(), nullable=False, server_default=""),
        )
        op.create_index("ix_program_baseline_rows_baseline_id", "program_baseline_rows", ["baseline_id"])
        op.create_index("ix_program_baseline_rows_row_no", "program_baseline_rows", ["row_no"])
        op.create_index("ix_program_baseline_rows_start_year", "program_baseline_rows", ["start_year"])
        op.create_index("ix_program_baseline_rows_end_year", "program_baseline_rows", ["end_year"])

    if "program_quarterly_forms" not in tables:
        op.create_table(
            "program_quarterly_forms",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("org_id", sa.Integer(), sa.ForeignKey("orgs.id"), nullable=False),
            sa.Column("form_type_id", sa.Integer(), sa.ForeignKey("program_form_types.id"), nullable=False),
            sa.Column("year", sa.Integer(), nullable=False),
            sa.Column("quarter", sa.Integer(), nullable=False),
            sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.UniqueConstraint("org_id", "form_type_id", "year", "quarter", name="uq_program_quarterly_org_type_year_q"),
        )
        op.create_index("ix_program_quarterly_forms_org_id", "program_quarterly_forms", ["org_id"])
        op.create_index("ix_program_quarterly_forms_form_type_id", "program_quarterly_forms", ["form_type_id"])
        op.create_index("ix_program_quarterly_forms_year", "program_quarterly_forms", ["year"])
        op.create_index("ix_program_quarterly_forms_quarter", "program_quarterly_forms", ["quarter"])
        op.create_index("ix_program_quarterly_forms_created_by_id", "program_quarterly_forms", ["created_by_id"])

    if "program_quarterly_rows" not in tables:
        op.create_table(
            "program_quarterly_rows",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("quarterly_form_id", sa.Integer(), sa.ForeignKey("program_quarterly_forms.id"), nullable=False),
            sa.Column("baseline_row_id", sa.Integer(), sa.ForeignKey("program_baseline_rows.id"), nullable=False),
            sa.Column("result_value", sa.Float(), nullable=True),
            sa.Column("actions_text", sa.Text(), nullable=False, server_default=""),
            sa.UniqueConstraint("quarterly_form_id", "baseline_row_id", name="uq_program_quarterly_row_unique"),
        )
        op.create_index("ix_program_quarterly_rows_quarterly_form_id", "program_quarterly_rows", ["quarterly_form_id"])
        op.create_index("ix_program_quarterly_rows_baseline_row_id", "program_quarterly_rows", ["baseline_row_id"])


def downgrade() -> None:
    # Intentionally no destructive downgrade
    pass
