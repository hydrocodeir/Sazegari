import enum
from sqlalchemy import String, Integer, Enum, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base

class Role(str, enum.Enum):
    SECRETARIAT_USER = "secretariat_user"
    SECRETARIAT_ADMIN = "secretariat_admin"

    ORG_PROV_EXPERT = "org_prov_expert"
    ORG_PROV_MANAGER = "org_prov_manager"
    ORG_COUNTY_EXPERT = "org_county_expert"
    ORG_COUNTY_MANAGER = "org_county_manager"

ROLE_LABELS = {
    Role.ORG_COUNTY_EXPERT: "کارشناس شهرستان",
    Role.ORG_COUNTY_MANAGER: "مدیر شهرستان",
    Role.ORG_PROV_EXPERT: "کارشناس استان",
    Role.ORG_PROV_MANAGER: "مدیر استان",
    Role.SECRETARIAT_USER: "کارشناس دبیرخانه",
    Role.SECRETARIAT_ADMIN: "مدیر دبیرخانه",
}

class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    full_name: Mapped[str] = mapped_column(String(120))
    username: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))

    role: Mapped[Role] = mapped_column(Enum(Role), index=True)

    org_id: Mapped[int | None] = mapped_column(ForeignKey("orgs.id"), nullable=True, index=True)
    county_id: Mapped[int | None] = mapped_column(ForeignKey("counties.id"), nullable=True, index=True)

    org = relationship("Org", back_populates="users")
    county = relationship("County", back_populates="users")

    @property
    def role_label(self) -> str:
        return ROLE_LABELS.get(self.role, self.role.value)
