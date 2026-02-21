from __future__ import annotations

import json

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import hash_password, verify_password
from app.db.models.org import Org
from app.db.models.county import County
from app.db.models.org_county import OrgCountyUnit
from app.db.models.form_template import FormTemplate
from app.db.models.user import User, Role


def _get_or_create_org(db: Session, name: str) -> Org:
    org = db.query(Org).filter(Org.name == name).first()
    if not org:
        org = Org(name=name)
        db.add(org)
        db.flush()  # populate org.id
    return org


def _get_or_create_county(db: Session, name: str) -> County:
    c = db.query(County).filter(County.name == name).first()
    if not c:
        c = County(name=name)
        db.add(c)
        db.flush()
    return c


def _get_or_create_unit(db: Session, org_id: int, county_id: int) -> OrgCountyUnit:
    u = (
        db.query(OrgCountyUnit)
        .filter(OrgCountyUnit.org_id == org_id, OrgCountyUnit.county_id == county_id)
        .first()
    )
    if not u:
        u = OrgCountyUnit(org_id=org_id, county_id=county_id)
        db.add(u)
        db.flush()
    return u


def _get_or_create_form(
    db: Session,
    *,
    org_id: int,
    title: str,
    scope: str,
    county_id: int | None,
    schema: dict,
) -> FormTemplate:
    f = (
        db.query(FormTemplate)
        .filter(
            FormTemplate.org_id == org_id,
            FormTemplate.title == title,
            FormTemplate.scope == scope,
            FormTemplate.county_id.is_(county_id) if county_id is None else FormTemplate.county_id == county_id,
        )
        .first()
    )
    if not f:
        f = FormTemplate(
            org_id=org_id,
            county_id=county_id,
            scope=scope,
            title=title,
            schema_json=json.dumps(schema, ensure_ascii=False),
        )
        db.add(f)
        db.flush()
    return f


def _upsert_user(
    db: Session,
    *,
    username: str,
    full_name: str,
    role: Role,
    org_id: int | None,
    county_id: int | None,
    password: str,
) -> User:
    u = db.query(User).filter(User.username == username).first()
    if not u:
        u = User(
            username=username,
            full_name=full_name,
            role=role,
            org_id=org_id,
            county_id=county_id,
            password_hash=hash_password(password),
            is_active=True,
        )
        db.add(u)
        db.flush()
        return u

    # keep it idempotent and also enforce requested sample values
    u.full_name = full_name
    u.role = role
    u.org_id = org_id
    u.county_id = county_id
    u.is_active = True

    try:
        if not verify_password(password, u.password_hash or ""):
            u.password_hash = hash_password(password)
    except Exception:
        u.password_hash = hash_password(password)

    db.flush()
    return u


def seed_sample(db: Session) -> None:
    """Idempotently seed a small sample dataset for quick manual testing."""

    pwd = settings.SAMPLE_SEED_PASSWORD or "123"

    # Orgs
    org_ab = _get_or_create_org(db, "شرکت آب منطقه‌ای خراسان رضوی")
    org_jh = _get_or_create_org(db, "سازمان جهاد کشاورزی خراسان رضوی")

    # Counties (units)
    c_ab_m = _get_or_create_county(db, "امور آب مشهد")
    c_ab_n = _get_or_create_county(db, "امور آب نیشابور")

    c_jh_m = _get_or_create_county(db, "جهاد کشاورزی مشهد")
    c_jh_n = _get_or_create_county(db, "جهاد کشاورزی نیشابور")

    # Relationships: Org <-> County unit
    _get_or_create_unit(db, org_ab.id, c_ab_m.id)
    _get_or_create_unit(db, org_ab.id, c_ab_n.id)

    _get_or_create_unit(db, org_jh.id, c_jh_m.id)
    _get_or_create_unit(db, org_jh.id, c_jh_n.id)

    # Forms (simple schema so UI has something to fill)
    county_schema = {
        "fields": [
            {"name": "desc", "label": "توضیحات", "type": "textarea", "required": True},
            {"name": "value", "label": "مقدار", "type": "number", "required": False},
        ]
    }
    prov_schema = {
        "fields": [
            {"name": "summary", "label": "خلاصه", "type": "textarea", "required": True},
            {"name": "note", "label": "یادداشت", "type": "text", "required": False},
        ]
    }

    # آبمن
    _get_or_create_form(db, org_id=org_ab.id, title="فرم شهرستانی 1", scope="all", county_id=None, schema=county_schema)
    _get_or_create_form(db, org_id=org_ab.id, title="فرم شهرستانی 2", scope="all", county_id=None, schema=county_schema)
    _get_or_create_form(db, org_id=org_ab.id, title="فرم استانی", scope="province", county_id=None, schema=prov_schema)

    # جهاد
    _get_or_create_form(db, org_id=org_jh.id, title="فرم شهرستانی 1", scope="all", county_id=None, schema=county_schema)
    _get_or_create_form(db, org_id=org_jh.id, title="فرم شهرستانی 2", scope="all", county_id=None, schema=county_schema)
    _get_or_create_form(db, org_id=org_jh.id, title="فرم استانی 1", scope="province", county_id=None, schema=prov_schema)
    _get_or_create_form(db, org_id=org_jh.id, title="فرم استانی 2", scope="province", county_id=None, schema=prov_schema)

    # Users (password for all: 123)
    # آبمن - استان
    _upsert_user(
        db,
        username="abman_prov_expert",
        full_name="آبمن - کارشناس استان",
        role=Role.ORG_PROV_EXPERT,
        org_id=org_ab.id,
        county_id=None,
        password=pwd,
    )
    _upsert_user(
        db,
        username="abman_prov_manager",
        full_name="آبمن - مدیر استان",
        role=Role.ORG_PROV_MANAGER,
        org_id=org_ab.id,
        county_id=None,
        password=pwd,
    )

    # آبمن - امور آب مشهد
    _upsert_user(
        db,
        username="abman_mashhad_expert",
        full_name="آبمن - امور آب مشهد - کارشناس",
        role=Role.ORG_COUNTY_EXPERT,
        org_id=org_ab.id,
        county_id=c_ab_m.id,
        password=pwd,
    )
    _upsert_user(
        db,
        username="abman_mashhad_manager",
        full_name="آبمن - امور آب مشهد - مدیر",
        role=Role.ORG_COUNTY_MANAGER,
        org_id=org_ab.id,
        county_id=c_ab_m.id,
        password=pwd,
    )

    # آبمن - امور آب نیشابور
    _upsert_user(
        db,
        username="abman_nishabur_expert",
        full_name="آبمن - امور آب نیشابور - کارشناس",
        role=Role.ORG_COUNTY_EXPERT,
        org_id=org_ab.id,
        county_id=c_ab_n.id,
        password=pwd,
    )
    _upsert_user(
        db,
        username="abman_nishabur_manager",
        full_name="آبمن - امور آب نیشابور - مدیر",
        role=Role.ORG_COUNTY_MANAGER,
        org_id=org_ab.id,
        county_id=c_ab_n.id,
        password=pwd,
    )

    # جهاد - استان
    _upsert_user(
        db,
        username="jahad_prov_expert",
        full_name="جهاد - کارشناس استان",
        role=Role.ORG_PROV_EXPERT,
        org_id=org_jh.id,
        county_id=None,
        password=pwd,
    )
    _upsert_user(
        db,
        username="jahad_prov_manager",
        full_name="جهاد - مدیر استان",
        role=Role.ORG_PROV_MANAGER,
        org_id=org_jh.id,
        county_id=None,
        password=pwd,
    )

    # جهاد - مشهد
    _upsert_user(
        db,
        username="jahad_mashhad_expert",
        full_name="جهاد - مشهد - کارشناس",
        role=Role.ORG_COUNTY_EXPERT,
        org_id=org_jh.id,
        county_id=c_jh_m.id,
        password=pwd,
    )
    _upsert_user(
        db,
        username="jahad_mashhad_manager",
        full_name="جهاد - مشهد - مدیر",
        role=Role.ORG_COUNTY_MANAGER,
        org_id=org_jh.id,
        county_id=c_jh_m.id,
        password=pwd,
    )

    # جهاد - نیشابور
    _upsert_user(
        db,
        username="jahad_nishabur_expert",
        full_name="جهاد - نیشابور - کارشناس",
        role=Role.ORG_COUNTY_EXPERT,
        org_id=org_jh.id,
        county_id=c_jh_n.id,
        password=pwd,
    )
    _upsert_user(
        db,
        username="jahad_nishabur_manager",
        full_name="جهاد - نیشابور - مدیر",
        role=Role.ORG_COUNTY_MANAGER,
        org_id=org_jh.id,
        county_id=c_jh_n.id,
        password=pwd,
    )

    # دبیرخانه سازگاری
    _upsert_user(
        db,
        username="secretariat_user",
        full_name="دبیرخانه سازگاری - کارشناس",
        role=Role.SECRETARIAT_USER,
        org_id=None,
        county_id=None,
        password=pwd,
    )
    _upsert_user(
        db,
        username="secretariat_admin",
        full_name="دبیرخانه سازگاری - مدیر",
        role=Role.SECRETARIAT_ADMIN,
        org_id=None,
        county_id=None,
        password=pwd,
    )


def main() -> int:
    # Allow manual execution:
    #   python -m app.scripts.seed_sample
    from app.db.session import SessionLocal

    db = SessionLocal()
    try:
        seed_sample(db)
        db.commit()
        print("Sample seed applied successfully.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
