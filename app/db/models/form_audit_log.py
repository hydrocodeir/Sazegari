from __future__ import annotations

from datetime import datetime

from sqlalchemy import Integer, ForeignKey, String, Text, DateTime, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class FormAuditLog(Base):
    """لاگ تغییرات فرم‌ها (ثبت/ویرایش/حذف).

    این لاگ برای همه انواع فرم‌ها (فرم‌های معمولی، پایش برنامه، تیپ فرم‌ها، ...)
    استفاده می‌شود تا مشخص باشد چه کسی چه عملیاتی انجام داده است.
    """

    __tablename__ = "form_audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    actor_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)

    # For scoping in UI
    org_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    county_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)

    # create/update/delete
    action: Mapped[str] = mapped_column(String(50), index=True)

    # submission/program_period_form/program_baseline/program_form_type/form_template/...
    entity: Mapped[str] = mapped_column(String(80), index=True)
    entity_id: Mapped[int] = mapped_column(Integer, index=True)

    before_json: Mapped[str] = mapped_column(Text, default="")
    after_json: Mapped[str] = mapped_column(Text, default="")
    comment: Mapped[str] = mapped_column(Text, default="")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
        index=True,
    )
