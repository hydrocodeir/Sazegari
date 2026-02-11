from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.auth.deps import get_current_user
from app.utils.badges import get_badge_count
from app.db.models.org import Org
from app.db.models.county import County
from app.db.models.org_county import OrgCountyUnit
from app.core.rbac import can_manage_masterdata, require

router = APIRouter(prefix="/org-counties", tags=["org_counties"])

@router.get("", response_class=HTMLResponse)
def page(request: Request, db: Session = Depends(get_db), user=Depends(get_current_user)):
    units = db.query(OrgCountyUnit).order_by(OrgCountyUnit.id.desc()).all()
    orgs = db.query(Org).order_by(Org.name.asc()).all()
    counties = db.query(County).order_by(County.name.asc()).all()
    return request.app.state.templates.TemplateResponse(
        "org_counties/index.html",
        {"request": request, "units": units, "orgs": orgs, "counties": counties, "user": user,"badge_count": get_badge_count(db, user)},
    )

@router.post("", response_class=HTMLResponse)
def create(
    request: Request,
    org_id: int = Form(...),
    county_id: int = Form(...),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    require(can_manage_masterdata(user))
    unit = OrgCountyUnit(org_id=org_id, county_id=county_id)
    db.add(unit)
    try:
        db.commit()
    except Exception:
        db.rollback()
        # اگر تکراری بود، چیزی اضافه نمی‌کنیم
        return HTMLResponse("")
    db.refresh(unit)
    return request.app.state.templates.TemplateResponse("org_counties/_row.html", {"request": request, "unit": unit})

@router.delete("/{unit_id}", response_class=HTMLResponse)
def delete(request: Request, unit_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    require(can_manage_masterdata(user))
    unit = db.get(OrgCountyUnit, unit_id)
    if unit:
        db.delete(unit)
        db.commit()
    return HTMLResponse("")
