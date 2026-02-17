from __future__ import annotations

from sqlalchemy import Integer, ForeignKey, UniqueConstraint, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class ProgramPeriodYearMode(Base):
    """قفل نوع بازه در یک سال برای یک تیپ فرم.

    طبق الزام: در یک سال برای یک تیپ فرم، نمی‌توان هم‌زمان سه‌ماهه و شش‌ماهه/سالانه ثبت کرد.
    این جدول با UniqueConstraint روی (org_id, form_type_id, year) این موضوع را enforce می‌کند.
    """

    __tablename__ = "program_period_year_modes"
    __table_args__ = (
        UniqueConstraint("org_id", "county_id", "form_type_id", "year", name="uq_program_period_year_mode"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("orgs.id"), index=True)
    # حوزه ثبت داده: 0 = استان، مقدار >0 = شهرستان
    county_id: Mapped[int] = mapped_column(Integer, default=0, server_default="0", index=True)
    form_type_id: Mapped[int] = mapped_column(ForeignKey("program_form_types.id"), index=True)
    year: Mapped[int] = mapped_column(Integer, index=True)
    period_type: Mapped[str] = mapped_column(String(16), index=True)  # quarter|half|year

    form_type = relationship("ProgramFormType")
    org = relationship("Org")
