"""add form audit logs

Revision ID: 20260221120000
Revises: 20260217193000
Create Date: 2026-02-21

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision = "20260221120000"
down_revision = "20260217193000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = inspect(bind)

    if "form_audit_logs" not in insp.get_table_names():
        op.create_table(
            "form_audit_logs",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("actor_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("org_id", sa.Integer(), nullable=True),
            sa.Column("county_id", sa.Integer(), nullable=True),
            sa.Column("action", sa.String(length=50), nullable=False),
            sa.Column("entity", sa.String(length=80), nullable=False),
            sa.Column("entity_id", sa.Integer(), nullable=False),
            sa.Column("before_json", sa.Text(), server_default="", nullable=False),
            sa.Column("after_json", sa.Text(), server_default="", nullable=False),
            sa.Column("comment", sa.Text(), server_default="", nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        )

    # Indexes (idempotent)
    def has_index(table: str, name: str) -> bool:
        try:
            return any(i.get("name") == name for i in insp.get_indexes(table))
        except Exception:
            return False

    for name, cols in [
        ("ix_form_audit_logs_actor_id", ["actor_id"]),
        ("ix_form_audit_logs_org_id", ["org_id"]),
        ("ix_form_audit_logs_county_id", ["county_id"]),
        ("ix_form_audit_logs_action", ["action"]),
        ("ix_form_audit_logs_entity", ["entity"]),
        ("ix_form_audit_logs_entity_id", ["entity_id"]),
        ("ix_form_audit_logs_created_at", ["created_at"]),
    ]:
        if not has_index("form_audit_logs", name):
            op.create_index(name, "form_audit_logs", cols)


def downgrade() -> None:
    bind = op.get_bind()
    insp = inspect(bind)
    if "form_audit_logs" in insp.get_table_names():
        op.drop_table("form_audit_logs")
