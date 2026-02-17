from __future__ import annotations

from sqlalchemy import Integer, ForeignKey, UniqueConstraint, Text, Float, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class ProgramPeriodForm(Base):
    """فرم دوره‌ای برنامه (سه‌ماهه/شش‌ماهه/سالانه).

    نکته: برای هر (ارگان، تیپ فرم، سال، نوع بازه، شماره بازه) فقط یک رکورد داریم.
    """

    __tablename__ = "program_period_forms"
    __table_args__ = (
        UniqueConstraint(
            "org_id",
            "county_id",
            "form_type_id",
            "year",
            "period_type",
            "period_no",
            name="uq_program_period_org_type_year_pt_pn",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("orgs.id"), index=True)
    # حوزه ثبت داده: 0 = استان، مقدار >0 = شهرستان
    # NOTE: از 0 استفاده می‌کنیم تا UniqueConstraint در MySQL برای scope استانی درست کار کند.
    county_id: Mapped[int] = mapped_column(Integer, default=0, server_default="0", index=True)
    form_type_id: Mapped[int] = mapped_column(ForeignKey("program_form_types.id"), index=True)

    # سال شمسی
    year: Mapped[int] = mapped_column(Integer, index=True)

    # نوع بازه: quarter | half | year
    period_type: Mapped[str] = mapped_column(String(16), index=True)
    # شماره بازه: quarter=>1..4, half=>1..2, year=>1
    period_no: Mapped[int] = mapped_column(Integer, index=True)

    created_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)

    form_type = relationship("ProgramFormType")
    created_by = relationship("User")
    rows = relationship("ProgramPeriodRow", back_populates="period_form", cascade="all, delete-orphan")


class ProgramPeriodRow(Base):
    """داده‌های هر ردیف در فرم دوره‌ای"""

    __tablename__ = "program_period_rows"
    __table_args__ = (
        UniqueConstraint("period_form_id", "baseline_row_id", name="uq_program_period_row_unique"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    period_form_id: Mapped[int] = mapped_column(ForeignKey("program_period_forms.id"), index=True)
    baseline_row_id: Mapped[int] = mapped_column(ForeignKey("program_baseline_rows.id"), index=True)

    # نتیجه/عملکرد همان بازه (می‌تواند خالی باشد)
    result_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    # اقدامات/شرح اقدامات همان بازه
    actions_text: Mapped[str] = mapped_column(Text, default="")

    period_form = relationship("ProgramPeriodForm", back_populates="rows")
    baseline_row = relationship("ProgramBaselineRow")
