from __future__ import annotations

from sqlalchemy import Integer, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Submission(Base):
    __tablename__ = "submissions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    # Form + scope
    form_id: Mapped[int] = mapped_column(ForeignKey("form_templates.id"), index=True)

    # For faster filtering + support for province-level submissions.
    # - county submissions: org_id + county_id are set, org_county_unit_id is set.
    # - province submissions: org_id is set, county_id is NULL, org_county_unit_id is NULL.
    org_id: Mapped[int] = mapped_column(ForeignKey("orgs.id"), index=True)
    county_id: Mapped[int | None] = mapped_column(ForeignKey("counties.id"), nullable=True, index=True)

    # Legacy (still used for county submissions)
    org_county_unit_id: Mapped[int | None] = mapped_column(
        ForeignKey("org_county_units.id"), nullable=True, index=True
    )

    created_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)

    payload_json: Mapped[str] = mapped_column(Text, default="{}")
