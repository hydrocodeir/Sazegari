from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.auth.deps import get_current_user
from app.utils.badges import get_badge_count
from app.db.models.org import Org
from app.core.rbac import can_manage_masterdata, require

router = APIRouter(prefix="/orgs", tags=["orgs"])

@router.get("", response_class=HTMLResponse)
def page(request: Request, db: Session = Depends(get_db), user=Depends(get_current_user)):
    orgs = db.query(Org).order_by(Org.id.desc()).all()
    return request.app.state.templates.TemplateResponse("orgs/index.html", {"request": request, "orgs": orgs, "user": user,"badge_count": get_badge_count(db, user)})

@router.post("", response_class=HTMLResponse)
def create(request: Request, name: str = Form(...), db: Session = Depends(get_db), user=Depends(get_current_user)):
    require(can_manage_masterdata(user))
    org = Org(name=name.strip())
    db.add(org)
    db.commit()
    db.refresh(org)
    return request.app.state.templates.TemplateResponse("orgs/_row.html", {"request": request, "org": org})

@router.delete("/{org_id}", response_class=HTMLResponse)
def delete(request: Request, org_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    require(can_manage_masterdata(user))
    org = db.get(Org, org_id)
    if org:
        db.delete(org)
        db.commit()
    return HTMLResponse("")
