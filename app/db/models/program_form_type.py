from sqlalchemy import Integer, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class ProgramFormType(Base):
    """
    تیپ فرم (Program Form Type)

    - برای هر ارگان، می‌تواند چند تیپ فرم تعریف شود.
    - متن مقدمه/نتیجه‌گیری از اینجا خوانده می‌شود.
    """
    __tablename__ = "program_form_types"
    __table_args__ = (
        UniqueConstraint("org_id", "title", name="uq_program_form_types_org_title"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("orgs.id"), index=True)

    title: Mapped[str] = mapped_column(String(200), index=True)

    intro_text: Mapped[str] = mapped_column(
        Text,
        default="مقدمه: (متن ثابت/قابل‌ویرایش توسط کارشناس استان)",
    )
    conclusion_text: Mapped[str] = mapped_column(
        Text,
        default="نتیجه‌گیری: (متن ثابت/قابل‌ویرایش توسط کارشناس استان)",
    )

    org = relationship("Org")
