from sqlalchemy import Integer, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base

class ReportSubmission(Base):
    __tablename__ = "report_submissions"
    __table_args__ = (UniqueConstraint("report_id", "submission_id", name="uq_report_submission"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    report_id: Mapped[int] = mapped_column(ForeignKey("reports.id"), index=True)
    submission_id: Mapped[int] = mapped_column(ForeignKey("submissions.id"), index=True)
