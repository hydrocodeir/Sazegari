from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
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



@router.get("/{org_id}/edit", response_class=HTMLResponse)
def edit_row(request: Request, org_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    require(can_manage_masterdata(user))
    org = db.get(Org, org_id)
    if not org:
        return HTMLResponse("یافت نشد", status_code=404)
    return request.app.state.templates.TemplateResponse("orgs/_row_edit.html", {"request": request, "org": org, "error": ""})

@router.get("/{org_id}/row", response_class=HTMLResponse)
def row(request: Request, org_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    require(can_manage_masterdata(user))
    org = db.get(Org, org_id)
    if not org:
        return HTMLResponse("یافت نشد", status_code=404)
    return request.app.state.templates.TemplateResponse("orgs/_row.html", {"request": request, "org": org})

@router.put("/{org_id}", response_class=HTMLResponse)
def update(request: Request, org_id: int, name: str = Form(...), db: Session = Depends(get_db), user=Depends(get_current_user)):
    require(can_manage_masterdata(user))
    org = db.get(Org, org_id)
    if not org:
        return HTMLResponse("یافت نشد", status_code=404)
    org.name = (name or "").strip()
    if not org.name:
        return request.app.state.templates.TemplateResponse("orgs/_row_edit.html", {"request": request, "org": org, "error": "نام نمی‌تواند خالی باشد."})
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return request.app.state.templates.TemplateResponse("orgs/_row_edit.html", {"request": request, "org": org, "error": "این نام قبلاً ثبت شده است."})
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
