from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.auth.deps import get_current_user
from app.utils.badges import get_badge_count
from app.db.models.county import County
from app.core.rbac import can_manage_masterdata, require

router = APIRouter(prefix="/counties", tags=["counties"])

@router.get("", response_class=HTMLResponse)
def page(request: Request, db: Session = Depends(get_db), user=Depends(get_current_user)):
    counties = db.query(County).order_by(County.id.desc()).all()
    return request.app.state.templates.TemplateResponse("counties/index.html", {"request": request, "counties": counties, "user": user,"badge_count": get_badge_count(db, user)})

@router.post("", response_class=HTMLResponse)
def create(request: Request, name: str = Form(...), db: Session = Depends(get_db), user=Depends(get_current_user)):
    require(can_manage_masterdata(user))
    c = County(name=name.strip())
    db.add(c)
    db.commit()
    db.refresh(c)
    return request.app.state.templates.TemplateResponse("counties/_row.html", {"request": request, "county": c})

@router.delete("/{county_id}", response_class=HTMLResponse)
def delete(request: Request, county_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    require(can_manage_masterdata(user))
    c = db.get(County, county_id)
    if c:
        db.delete(c)
        db.commit()
    return HTMLResponse("")
