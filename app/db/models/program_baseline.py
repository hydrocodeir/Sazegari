from __future__ import annotations

from sqlalchemy import Integer, ForeignKey, String, UniqueConstraint, Text, Float
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class ProgramBaseline(Base):
    """فرم اولیه برنامه پایش - یک بار برای هر تیپ فرم در هر ارگان"""
    __tablename__ = "program_baselines"
    __table_args__ = (
        UniqueConstraint("org_id", "form_type_id", name="uq_program_baselines_org_type"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("orgs.id"), index=True)
    form_type_id: Mapped[int] = mapped_column(ForeignKey("program_form_types.id"), index=True)

    created_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)

    form_type = relationship("ProgramFormType")
    created_by = relationship("User")

    rows = relationship("ProgramBaselineRow", back_populates="baseline", cascade="all, delete-orphan")


class ProgramBaselineRow(Base):
    """ردیف‌های فرم اولیه (پروژه‌ها)"""
    __tablename__ = "program_baseline_rows"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    baseline_id: Mapped[int] = mapped_column(ForeignKey("program_baselines.id"), index=True)

    # شماره/شناسه ردیف در خروجی گزارش (برای نمایش)
    row_no: Mapped[int] = mapped_column(Integer, index=True)

    title: Mapped[str] = mapped_column(String(400))
    unit: Mapped[str] = mapped_column(String(80), default="")

    start_year: Mapped[int] = mapped_column(Integer, index=True)
    end_year: Mapped[int] = mapped_column(Integer, index=True)

    # هدف تا سال پیش‌بینی خاتمه
    target_value: Mapped[float] = mapped_column(Float)

    notes: Mapped[str] = mapped_column(Text, default="")

    baseline = relationship("ProgramBaseline", back_populates="rows")
