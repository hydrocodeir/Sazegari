from sqlalchemy import Integer, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base

class OrgCountyUnit(Base):
    __tablename__ = "org_county_units"
    __table_args__ = (UniqueConstraint("org_id", "county_id", name="uq_org_county"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("orgs.id"), index=True)
    county_id: Mapped[int] = mapped_column(ForeignKey("counties.id"), index=True)

    org = relationship("Org")
    county = relationship("County")
