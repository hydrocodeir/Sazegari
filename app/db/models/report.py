import enum
from sqlalchemy import Integer, Enum, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base

class ReportStatus(str, enum.Enum):
    DRAFT = "draft"
    COUNTY_EXPERT_REVIEW = "county_expert_review"
    COUNTY_MANAGER_REVIEW = "county_manager_review"
    PROV_EXPERT_REVIEW = "prov_expert_review"
    PROV_MANAGER_REVIEW = "prov_manager_review"
    # مسیر گزارش استانی در دبیرخانه دو مرحله‌ای است
    SECRETARIAT_USER_REVIEW = "secretariat_user_review"
    SECRETARIAT_ADMIN_REVIEW = "secretariat_admin_review"
    # سازگاری با نسخه‌های قبلی
    SECRETARIAT_REVIEW = "secretariat_review"
    NEEDS_REVISION = "needs_revision"
    FINAL_APPROVED = "final_approved"


class ReportKind(str, enum.Enum):
    """نوع گزارش

    - COUNTY: گزارش شهرستان (توسط کارشناس شهرستان ساخته می‌شود)
    - PROVINCIAL: گزارش جامع استانی (توسط کارشناس استان ساخته می‌شود)
    """

    COUNTY = "county"
    PROVINCIAL = "provincial"



KIND_LABELS = {
    ReportKind.COUNTY: "شهرستانی",
    ReportKind.PROVINCIAL: "استانی",
}

STATUS_LABELS = {
    ReportStatus.DRAFT: "پیش‌نویس",
    ReportStatus.COUNTY_EXPERT_REVIEW: "بررسی کارشناس شهرستان",
    ReportStatus.COUNTY_MANAGER_REVIEW: "بررسی مدیر شهرستان",
    ReportStatus.PROV_EXPERT_REVIEW: "بررسی کارشناس استان",
    ReportStatus.PROV_MANAGER_REVIEW: "بررسی مدیر استان",
    ReportStatus.SECRETARIAT_USER_REVIEW: "بررسی کارشناس دبیرخانه",
    ReportStatus.SECRETARIAT_ADMIN_REVIEW: "بررسی مدیر دبیرخانه",
    ReportStatus.SECRETARIAT_REVIEW: "بررسی دبیرخانه",
    ReportStatus.NEEDS_REVISION: "نیاز به اصلاح",
    ReportStatus.FINAL_APPROVED: "تایید نهایی",
}

class Report(Base):
    __tablename__ = "reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("orgs.id"), index=True)
    # برای گزارش استانی county_id مقدار ندارد
    county_id: Mapped[int | None] = mapped_column(ForeignKey("counties.id"), nullable=True, index=True)
    created_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    current_owner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)

    org = relationship("Org")
    county = relationship("County")

    kind: Mapped[ReportKind] = mapped_column(Enum(ReportKind), index=True, default=ReportKind.COUNTY)
    status: Mapped[ReportStatus] = mapped_column(Enum(ReportStatus), index=True, default=ReportStatus.DRAFT)
    content_json: Mapped[str] = mapped_column(Text, default="{}")
    note: Mapped[str] = mapped_column(Text, default="")

    @property
    def kind_label(self) -> str:
        return KIND_LABELS.get(self.kind, getattr(self.kind, "value", str(self.kind)))

    @property
    def status_label(self) -> str:
        return STATUS_LABELS.get(self.status, getattr(self.status, "value", str(self.status)))

