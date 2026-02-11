"""update reports workflow and add audit log

Revision ID: 20260211120000
Revises: 20260210194826
Create Date: 2026-02-11T12:00:00Z
"""

from alembic import op
import sqlalchemy as sa


revision = "20260211120000"
down_revision = "20260210194826"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name

    # 1) reports: add kind column and make county_id nullable
    with op.batch_alter_table("reports") as batch:
        batch.add_column(sa.Column("kind", sa.String(length=50), nullable=False, server_default="county"))
        try:
            batch.alter_column("county_id", existing_type=sa.Integer(), nullable=True)
        except Exception:
            # Some dialects may not support this; ignore and rely on fresh install.
            pass

    # 2) report_audit_logs table
    op.create_table(
        "report_audit_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("report_id", sa.Integer(), sa.ForeignKey("reports.id"), nullable=False, index=True),
        sa.Column("actor_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False, index=True),
        sa.Column("action", sa.String(length=50), nullable=False),
        sa.Column("field", sa.String(length=80), nullable=False, server_default=""),
        sa.Column("before_json", sa.Text(), nullable=False, server_default=""),
        sa.Column("after_json", sa.Text(), nullable=False, server_default=""),
        sa.Column("comment", sa.Text(), nullable=False, server_default=""),
    )
    op.create_index("ix_report_audit_logs_report_id", "report_audit_logs", ["report_id"])
    op.create_index("ix_report_audit_logs_actor_id", "report_audit_logs", ["actor_id"])


def downgrade() -> None:
    op.drop_index("ix_report_audit_logs_actor_id", table_name="report_audit_logs")
    op.drop_index("ix_report_audit_logs_report_id", table_name="report_audit_logs")
    op.drop_table("report_audit_logs")
    with op.batch_alter_table("reports") as batch:
        batch.drop_column("kind")