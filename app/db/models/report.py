import enum
from sqlalchemy import Integer, Enum, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base

class ReportStatus(str, enum.Enum):
    DRAFT = "draft"
    COUNTY_EXPERT_REVIEW = "county_expert_review"
    COUNTY_MANAGER_REVIEW = "county_manager_review"
    PROV_EXPERT_REVIEW = "prov_expert_review"
    PROV_MANAGER_REVIEW = "prov_manager_review"
    SECRETARIAT_REVIEW = "secretariat_review"
    NEEDS_REVISION = "needs_revision"
    FINAL_APPROVED = "final_approved"

class Report(Base):
    __tablename__ = "reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("orgs.id"), index=True)
    county_id: Mapped[int] = mapped_column(ForeignKey("counties.id"), index=True)
    created_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    current_owner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)

    status: Mapped[ReportStatus] = mapped_column(Enum(ReportStatus), index=True, default=ReportStatus.DRAFT)
    content_json: Mapped[str] = mapped_column(Text, default="{}")
    note: Mapped[str] = mapped_column(Text, default="")
