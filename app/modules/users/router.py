from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.auth.deps import get_current_user
from app.utils.badges import get_badge_count
from app.core.rbac import require, can_manage_masterdata
from app.core.security import hash_password

from app.db.models.user import User, Role
from app.db.models.org import Org
from app.db.models.county import County

router = APIRouter(prefix="/users", tags=["users"])

def _validate_role_context(role: Role, org_id: int | None, county_id: int | None) -> str | None:
    # Return error message if invalid, else None
    if role in (Role.SECRETARIAT_ADMIN, Role.SECRETARIAT_USER):
        return None  # org/county optional for now

    if role in (Role.ORG_PROV_EXPERT, Role.ORG_PROV_MANAGER):
        if not org_id:
            return "برای نقش‌های استانی باید ارگان انتخاب شود."
        return None

    if role in (Role.ORG_COUNTY_EXPERT, Role.ORG_COUNTY_MANAGER):
        if not org_id or not county_id:
            return "برای نقش‌های شهرستانی باید ارگان و شهرستان انتخاب شود."
        return None

    return None

@router.get("", response_class=HTMLResponse)
def page(request: Request, db: Session = Depends(get_db), user=Depends(get_current_user)):
    require(can_manage_masterdata(user))
    users = db.query(User).order_by(User.id.desc()).all()
    orgs = db.query(Org).order_by(Org.name.asc()).all()
    counties = db.query(County).order_by(County.name.asc()).all()
    roles = [r.value for r in Role]
    return request.app.state.templates.TemplateResponse(
        "users/index.html",
        {"request": request, "users": users, "orgs": orgs, "counties": counties, "roles": roles, "user": user,"badge_count": get_badge_count(db, user)},
    )

@router.post("", response_class=HTMLResponse)
def create(
    request: Request,
    full_name: str = Form(...),
    username: str = Form(...),
    password: str = Form(...),
    role: str = Form(...),
    org_id: str = Form(""),
    county_id: str = Form(""),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    require(can_manage_masterdata(user))

    try:
        role_enum = Role(role)
    except Exception:
        return request.app.state.templates.TemplateResponse(
            "users/_row_error.html",
            {"request": request, "error": "نقش نامعتبر است."},
            status_code=400,
        )

    oid = int(org_id) if org_id.strip() else None
    cid = int(county_id) if county_id.strip() else None

    err = _validate_role_context(role_enum, oid, cid)
    if err:
        return request.app.state.templates.TemplateResponse(
            "users/_row_error.html",
            {"request": request, "error": err},
            status_code=400,
        )

    # unique username
    if db.query(User).filter(User.username == username.strip()).first():
        return request.app.state.templates.TemplateResponse(
            "users/_row_error.html",
            {"request": request, "error": "این نام کاربری قبلاً ثبت شده است."},
            status_code=400,
        )

    u = User(
        full_name=full_name.strip(),
        username=username.strip(),
        password_hash=hash_password(password),
        role=role_enum,
        org_id=oid,
        county_id=cid,
    )
    db.add(u)
    db.commit()
    db.refresh(u)

    return request.app.state.templates.TemplateResponse("users/_row.html", {"request": request, "u": u})

@router.get("/{user_id}/edit", response_class=HTMLResponse)
def edit_page(request: Request, user_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    require(can_manage_masterdata(user))
    u = db.get(User, user_id)
    orgs = db.query(Org).order_by(Org.name.asc()).all()
    counties = db.query(County).order_by(County.name.asc()).all()
    roles = [r.value for r in Role]
    return request.app.state.templates.TemplateResponse(
        "users/edit.html",
        {"request": request, "u": u, "orgs": orgs, "counties": counties, "roles": roles, "user": user,"badge_count": get_badge_count(db, user)},
    )

@router.post("/{user_id}/edit")
def edit_save(
    request: Request,
    user_id: int,
    full_name: str = Form(...),
    username: str = Form(...),
    role: str = Form(...),
    org_id: str = Form(""),
    county_id: str = Form(""),
    new_password: str = Form(""),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    require(can_manage_masterdata(user))
    u = db.get(User, user_id)
    if not u:
        return RedirectResponse("/users", status_code=303)

    try:
        role_enum = Role(role)
    except Exception:
        return request.app.state.templates.TemplateResponse(
            "users/edit.html",
            {"request": request, "u": u, "error": "نقش نامعتبر است.", "orgs": db.query(Org).all(), "counties": db.query(County).all(), "roles": [r.value for r in Role], "user": user,"badge_count": get_badge_count(db, user)},
            status_code=400,
        )

    oid = int(org_id) if org_id.strip() else None
    cid = int(county_id) if county_id.strip() else None

    err = _validate_role_context(role_enum, oid, cid)
    if err:
        return request.app.state.templates.TemplateResponse(
            "users/edit.html",
            {"request": request, "u": u, "error": err, "orgs": db.query(Org).all(), "counties": db.query(County).all(), "roles": [r.value for r in Role], "user": user,"badge_count": get_badge_count(db, user)},
            status_code=400,
        )

    # username uniqueness (excluding self)
    existing = db.query(User).filter(User.username == username.strip(), User.id != u.id).first()
    if existing:
        return request.app.state.templates.TemplateResponse(
            "users/edit.html",
            {"request": request, "u": u, "error": "این نام کاربری قبلاً ثبت شده است.", "orgs": db.query(Org).all(), "counties": db.query(County).all(), "roles": [r.value for r in Role], "user": user,"badge_count": get_badge_count(db, user)},
            status_code=400,
        )

    u.full_name = full_name.strip()
    u.username = username.strip()
    u.role = role_enum
    u.org_id = oid
    u.county_id = cid

    if new_password.strip():
        u.password_hash = hash_password(new_password.strip())

    db.commit()
    return RedirectResponse("/users", status_code=303)

@router.delete("/{user_id}", response_class=HTMLResponse)
def delete(request: Request, user_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    require(can_manage_masterdata(user))
    u = db.get(User, user_id)
    if u:
        db.delete(u)
        db.commit()
    return HTMLResponse("")


@router.post("/{user_id}/toggle-active", response_class=HTMLResponse)
def toggle_active(request: Request, user_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    # Only secretariat_admin (masterdata.manage in policy) can manage users
    require(can_manage_masterdata(user))
    u = db.get(User, user_id)
    require(u is not None, "کاربر یافت نشد", 404)
    # do not allow disabling yourself (optional safety)
    if u.id == user.id:
        return request.app.state.templates.TemplateResponse(
            "users/_row_error.html",
            {"request": request, "error": "امکان غیرفعال‌کردن حساب خودتان وجود ندارد."},
            status_code=400,
        )
    # toggle
    if hasattr(u, "is_active"):
        u.is_active = not bool(u.is_active)
    db.commit()
    db.refresh(u)
    return request.app.state.templates.TemplateResponse("users/_row.html", {"request": request, "u": u})
