from sqlalchemy import Integer, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base

class FormTemplate(Base):
    __tablename__ = "form_templates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("orgs.id"), index=True)
    county_id: Mapped[int | None] = mapped_column(ForeignKey("counties.id"), nullable=True, index=True)

    title: Mapped[str] = mapped_column(String(200), index=True)
    schema_json: Mapped[str] = mapped_column(Text, default="{}")
