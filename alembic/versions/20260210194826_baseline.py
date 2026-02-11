"""baseline

Revision ID: 20260210194826
Revises:
Create Date: 2026-02-10T19:48:26.136393Z
"""

from alembic import op
import sqlalchemy as sa  # noqa: F401

# revision identifiers, used by Alembic.
revision = "20260210194826"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Import all models so SQLAlchemy metadata is fully populated.
    # NOTE: app.db.models.__init__ imports every model file.
    from app.db.base import Base
    import app.db.models  # noqa: F401

    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)


def downgrade() -> None:
    # Downgrading baseline is intentionally a no-op to avoid accidental data loss.
    # If you need destructive rollback, create explicit downgrade migrations.
    pass
