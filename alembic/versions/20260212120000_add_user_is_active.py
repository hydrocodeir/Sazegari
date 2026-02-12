"""add users.is_active

Revision ID: 20260212120000
Revises: 20260211123000
Create Date: 2026-02-12
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260212120000"
down_revision = "20260211123000"
branch_labels = None
depends_on = None


def _column_exists(table_name: str, column_name: str) -> bool:
    """MySQL-safe existence check to make this migration idempotent.

    In some environments the column may already exist (e.g. restored DB, manual ALTER,
    or schema drift). Without this guard, MySQL raises:
    (1060, "Duplicate column name ...").
    """
    bind = op.get_bind()
    q = sa.text(
        """
        SELECT COUNT(*)
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = :t
          AND COLUMN_NAME = :c
        """
    )
    return int(bind.execute(q, {"t": table_name, "c": column_name}).scalar() or 0) > 0


def _index_exists(table_name: str, index_name: str) -> bool:
    bind = op.get_bind()
    q = sa.text(
        """
        SELECT COUNT(*)
        FROM INFORMATION_SCHEMA.STATISTICS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = :t
          AND INDEX_NAME = :i
        """
    )
    return int(bind.execute(q, {"t": table_name, "i": index_name}).scalar() or 0) > 0


def upgrade() -> None:
    # Idempotent upgrade: only apply if missing.
    if not _column_exists("users", "is_active"):
        op.add_column(
            "users",
            sa.Column(
                "is_active",
                sa.Boolean(),
                server_default=sa.text("1"),
                nullable=False,
            ),
        )
    if not _index_exists("users", "ix_users_is_active"):
        op.create_index("ix_users_is_active", "users", ["is_active"], unique=False)


def downgrade() -> None:
    # Best-effort downgrade for drifted schemas.
    if _index_exists("users", "ix_users_is_active"):
        op.drop_index("ix_users_is_active", table_name="users")
    if _column_exists("users", "is_active"):
        op.drop_column("users", "is_active")
