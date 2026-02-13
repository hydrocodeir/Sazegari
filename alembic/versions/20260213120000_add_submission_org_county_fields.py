"""add org_id/county_id to submissions and allow province-level submissions

Revision ID: 20260213120000
Revises: 20260212120000
Create Date: 2026-02-13
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text


revision = "20260213120000"
down_revision = "20260212120000"
branch_labels = None
depends_on = None


def _has_fk(insp, table: str, name: str) -> bool:
    try:
        fks = insp.get_foreign_keys(table)
    except Exception:
        return False
    return any((fk.get("name") == name) for fk in fks)


def upgrade() -> None:
    bind = op.get_bind()
    insp = inspect(bind)

    cols = {c["name"] for c in insp.get_columns("submissions")}

    if "org_id" not in cols:
        op.add_column("submissions", sa.Column("org_id", sa.Integer(), nullable=True))

    if "county_id" not in cols:
        op.add_column("submissions", sa.Column("county_id", sa.Integer(), nullable=True))

    # Make org_county_unit_id nullable (needed for province submissions)
    try:
        oc_col = next(c for c in insp.get_columns("submissions") if c["name"] == "org_county_unit_id")
        if not oc_col.get("nullable", True):
            op.alter_column(
                "submissions",
                "org_county_unit_id",
                existing_type=sa.Integer(),
                nullable=True,
            )
    except StopIteration:
        pass

    idxs = {i["name"] for i in insp.get_indexes("submissions")}
    if "ix_submissions_org_id" not in idxs:
        op.create_index("ix_submissions_org_id", "submissions", ["org_id"], unique=False)
    if "ix_submissions_county_id" not in idxs:
        op.create_index("ix_submissions_county_id", "submissions", ["county_id"], unique=False)

    # Foreign keys (idempotent)
    if not _has_fk(insp, "submissions", "fk_submissions_org_id_orgs"):
        op.create_foreign_key(
            "fk_submissions_org_id_orgs",
            "submissions",
            "orgs",
            ["org_id"],
            ["id"],
        )

    if not _has_fk(insp, "submissions", "fk_submissions_county_id_counties"):
        op.create_foreign_key(
            "fk_submissions_county_id_counties",
            "submissions",
            "counties",
            ["county_id"],
            ["id"],
        )

    # Backfill org_id/county_id for existing rows (from org_county_units)
    # This statement is MySQL-compatible.
    op.execute(
        "UPDATE submissions s "
        "JOIN org_county_units u ON s.org_county_unit_id = u.id "
        "SET s.org_id = u.org_id, s.county_id = u.county_id "
        "WHERE s.org_county_unit_id IS NOT NULL AND (s.org_id IS NULL OR s.county_id IS NULL)"
    )

    # If backfill succeeded, we can safely enforce NOT NULL on org_id.
    try:
        missing = bind.execute(text("SELECT COUNT(*) FROM submissions WHERE org_id IS NULL")).scalar()  # type: ignore
        if missing == 0:
            op.alter_column("submissions", "org_id", existing_type=sa.Integer(), nullable=False)
    except Exception:
        # Keep as nullable if dialect doesn't support / errors.
        pass


def downgrade() -> None:
    bind = op.get_bind()
    insp = inspect(bind)

    # Best-effort downgrade (kept safe / idempotent)
    try:
        fks = {fk.get("name") for fk in insp.get_foreign_keys("submissions")}
        if "fk_submissions_county_id_counties" in fks:
            op.drop_constraint("fk_submissions_county_id_counties", "submissions", type_="foreignkey")
        if "fk_submissions_org_id_orgs" in fks:
            op.drop_constraint("fk_submissions_org_id_orgs", "submissions", type_="foreignkey")
    except Exception:
        pass

    idxs = {i["name"] for i in insp.get_indexes("submissions")}
    if "ix_submissions_county_id" in idxs:
        op.drop_index("ix_submissions_county_id", table_name="submissions")
    if "ix_submissions_org_id" in idxs:
        op.drop_index("ix_submissions_org_id", table_name="submissions")

    cols = {c["name"] for c in insp.get_columns("submissions")}
    if "county_id" in cols:
        op.drop_column("submissions", "county_id")
    if "org_id" in cols:
        op.drop_column("submissions", "org_id")

    # We don't force org_county_unit_id back to NOT NULL (may contain province rows).
