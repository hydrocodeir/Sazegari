"""add scope to form_templates

Revision ID: 20260211123000
Revises: 20260211120000
Create Date: 2026-02-11
"""

from alembic import op
import sqlalchemy as sa


revision = "20260211123000"
down_revision = "20260211120000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # اضافه کردن ستون scope
    op.add_column(
        "form_templates",
        sa.Column("scope", sa.String(length=20), nullable=False, server_default="all"),
    )
    op.create_index("ix_form_templates_scope", "form_templates", ["scope"], unique=False)

    # مقداردهی برای داده‌های قبلی:
    # - اگر county_id دارد => county
    # - اگر ندارد => all
    op.execute("UPDATE form_templates SET scope='county' WHERE county_id IS NOT NULL")
    op.execute("UPDATE form_templates SET scope='all' WHERE county_id IS NULL")


def downgrade() -> None:
    op.drop_index("ix_form_templates_scope", table_name="form_templates")
    op.drop_column("form_templates", "scope")
