from sqlalchemy import Integer, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base

class Submission(Base):
    __tablename__ = "submissions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    form_id: Mapped[int] = mapped_column(ForeignKey("form_templates.id"), index=True)
    org_county_unit_id: Mapped[int] = mapped_column(ForeignKey("org_county_units.id"), index=True)
    created_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)

    payload_json: Mapped[str] = mapped_column(Text, default="{}")
