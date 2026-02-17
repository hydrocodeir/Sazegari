from __future__ import annotations

from sqlalchemy import Integer, ForeignKey, UniqueConstraint, Text, Float
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class ProgramQuarterlyForm(Base):
    """فرم سه‌ماهه"""
    __tablename__ = "program_quarterly_forms"
    __table_args__ = (
        UniqueConstraint("org_id", "form_type_id", "year", "quarter", name="uq_program_quarterly_org_type_year_q"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("orgs.id"), index=True)
    form_type_id: Mapped[int] = mapped_column(ForeignKey("program_form_types.id"), index=True)

    # سال و فصل شمسی
    year: Mapped[int] = mapped_column(Integer, index=True)
    quarter: Mapped[int] = mapped_column(Integer, index=True)  # 1..4

    created_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)

    form_type = relationship("ProgramFormType")
    created_by = relationship("User")

    rows = relationship("ProgramQuarterlyRow", back_populates="quarterly", cascade="all, delete-orphan")


class ProgramQuarterlyRow(Base):
    """داده‌های هر ردیف در فرم سه‌ماهه"""
    __tablename__ = "program_quarterly_rows"
    __table_args__ = (
        UniqueConstraint("quarterly_form_id", "baseline_row_id", name="uq_program_quarterly_row_unique"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    quarterly_form_id: Mapped[int] = mapped_column(ForeignKey("program_quarterly_forms.id"), index=True)
    baseline_row_id: Mapped[int] = mapped_column(ForeignKey("program_baseline_rows.id"), index=True)

    # نتیجه/عملکرد همان سه‌ماهه - می‌تواند خالی باشد
    result_value: Mapped[float | None] = mapped_column(Float, nullable=True)

    # اقدامات/شرح اقدامات همان سه‌ماهه - می‌تواند خالی باشد
    actions_text: Mapped[str] = mapped_column(Text, default="")

    quarterly = relationship("ProgramQuarterlyForm", back_populates="rows")
    baseline_row = relationship("ProgramBaselineRow")
