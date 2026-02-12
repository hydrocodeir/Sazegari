"""add scope to form_templates

Revision ID: 20260211123000
Revises: 20260211120000
Create Date: 2026-02-11
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260211123000"
down_revision = "20260211120000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = inspect(bind)

    cols = {c["name"] for c in insp.get_columns("form_templates")}
    if "scope" not in cols:
        # اضافه کردن ستون scope (idempotent)
        op.add_column(
            "form_templates",
            sa.Column("scope", sa.String(length=20), nullable=False, server_default="all"),
        )

    idxs = {i["name"] for i in insp.get_indexes("form_templates")}
    if "ix_form_templates_scope" not in idxs:
        op.create_index("ix_form_templates_scope", "form_templates", ["scope"], unique=False)

    # مقداردهی برای داده‌های قبلی:
    # - اگر county_id دارد => county
    # - اگر ندارد => all
    op.execute("UPDATE form_templates SET scope='county' WHERE county_id IS NOT NULL")
    op.execute("UPDATE form_templates SET scope='all' WHERE county_id IS NULL")


def downgrade() -> None:
    bind = op.get_bind()
    insp = inspect(bind)

    idxs = {i["name"] for i in insp.get_indexes("form_templates")}
    if "ix_form_templates_scope" in idxs:
        op.drop_index("ix_form_templates_scope", table_name="form_templates")

    cols = {c["name"] for c in insp.get_columns("form_templates")}
    if "scope" in cols:
        op.drop_column("form_templates", "scope")
