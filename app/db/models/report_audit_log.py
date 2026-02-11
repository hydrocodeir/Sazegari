from sqlalchemy import Integer, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ReportAuditLog(Base):
    """لاگ تغییرات محتوای گزارش.

    این لاگ مستقل از WorkflowLog است و برای ثبت ایجاد/ویرایش/حذف گزارش و همچنین
    تغییرات بخش‌های مختلف (متن، اتصال فرم‌ها، پیوست‌ها و ... ) استفاده می‌شود.
    """

    __tablename__ = "report_audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    report_id: Mapped[int] = mapped_column(ForeignKey("reports.id"), index=True)
    actor_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)

    action: Mapped[str] = mapped_column(String(50))  # create/update/delete/attach/...
    field: Mapped[str] = mapped_column(String(80), default="")
    before_json: Mapped[str] = mapped_column(Text, default="")
    after_json: Mapped[str] = mapped_column(Text, default="")
    comment: Mapped[str] = mapped_column(Text, default="")
