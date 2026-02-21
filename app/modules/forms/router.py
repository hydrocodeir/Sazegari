from __future__ import annotations

import json

from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.auth.deps import get_current_user
from app.utils.badges import get_badge_count
from app.utils.form_audit import add_form_audit_log
from app.db.models.form_template import FormTemplate
from app.db.models.org import Org
from app.db.models.county import County
from app.db.models.user import Role
from app.core.rbac import can_create_form, is_secretariat, is_county, require

router = APIRouter(prefix="/forms", tags=["forms"])


@router.get("", response_class=HTMLResponse)
def page(request: Request, db: Session = Depends(get_db), user=Depends(get_current_user)):
    q = db.query(FormTemplate).order_by(FormTemplate.id.desc())
    if not is_secretariat(user):
        q = q.filter(FormTemplate.org_id == user.org_id)
        if is_county(user):
            # شهرستان فقط فرم‌های عمومی + شهرستان خودش (و نه فرم‌های استانی)
            q = q.filter(
                (FormTemplate.scope == "all")
                | ((FormTemplate.scope == "county") & (FormTemplate.county_id == user.county_id))
            )
    forms = q.all()
    orgs = db.query(Org).order_by(Org.name.asc()).all()
    counties = db.query(County).order_by(County.name.asc()).all()
    return request.app.state.templates.TemplateResponse(
        "forms/index.html",
        {
            "request": request,
            "forms": forms,
            "orgs": orgs,
            "counties": counties,
            "user": user,
            "can_create_form": can_create_form(user),
            "badge_count": get_badge_count(db, user),
        },
    )


@router.post("", response_class=HTMLResponse)
def create(
    request: Request,
    org_id: int = Form(...),
    title: str = Form(...),
    county_id: str = Form(""),
    schema_text: str = Form("{}"),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    require(can_create_form(user))

    # Non-secretariat can only create templates inside their own org
    if not is_secretariat(user):
        require(org_id == user.org_id, "دسترسی غیرمجاز", 403)

    # county_id می‌تواند یکی از موارد زیر باشد:
    # ""         => همه شهرستان‌ها (scope=all)
    # "province" => استان (scope=province)
    # "<id>"     => یک شهرستان مشخص (scope=county)
    scope = "all"
    cid = None
    if (county_id or "").strip() == "province":
        scope = "province"
        cid = None
    elif (county_id or "").strip():
        scope = "county"
        cid = int(county_id)

    # Province templates are created/managed only by Secretariat Admin
    if scope == "province":
        require(
            user.role == Role.SECRETARIAT_ADMIN,
            "ایجاد/ویرایش فرم استانی فقط توسط مدیر دبیرخانه امکان‌پذیر است.",
            403,
        )

    # validate schema JSON
    try:
        json.loads(schema_text or "{}")
    except Exception:
        schema_text = "{}"

    f = FormTemplate(org_id=org_id, county_id=cid, scope=scope, title=title.strip(), schema_json=schema_text)
    db.add(f)
    db.flush()

    add_form_audit_log(
        db,
        actor_id=user.id,
        action="create",
        entity="form_template",
        entity_id=f.id,
        org_id=f.org_id,
        county_id=f.county_id,
        before=None,
        after={"title": f.title, "scope": f.scope, "county_id": f.county_id, "schema_json": f.schema_json},
    )

    db.commit()
    db.refresh(f)

    counties = db.query(County).order_by(County.name.asc()).all()
    return request.app.state.templates.TemplateResponse(
        "forms/_row.html",
        {"request": request, "form": f, "can_create_form": True, "counties": counties},
    )


@router.get("/{form_id}/edit", response_class=HTMLResponse)
def edit_page(request: Request, form_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    require(can_create_form(user))
    f = db.get(FormTemplate, form_id)
    require(f is not None, "فرم یافت نشد", 404)

    if not is_secretariat(user):
        require(f.org_id == user.org_id, "دسترسی غیرمجاز", 403)

    # Province templates are managed only by Secretariat Admin
    if f.scope == "province":
        require(
            user.role == Role.SECRETARIAT_ADMIN,
            "ویرایش فرم استانی فقط توسط مدیر دبیرخانه امکان‌پذیر است.",
            403,
        )

    orgs = db.query(Org).order_by(Org.name.asc()).all()
    counties = db.query(County).order_by(County.name.asc()).all()
    return request.app.state.templates.TemplateResponse(
        "forms/edit.html",
        {
            "request": request,
            "form": f,
            "orgs": orgs,
            "counties": counties,
            "user": user,
            "badge_count": get_badge_count(db, user),
        },
    )


@router.post("/{form_id}/edit")
def edit_save(
    request: Request,
    form_id: int,
    org_id: int = Form(...),
    title: str = Form(...),
    county_id: str = Form(""),
    schema_text: str = Form("{}"),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    require(can_create_form(user))

    f = db.get(FormTemplate, form_id)
    require(f is not None, "فرم یافت نشد", 404)

    if not is_secretariat(user):
        require(f.org_id == user.org_id, "دسترسی غیرمجاز", 403)
        require(org_id == user.org_id, "دسترسی غیرمجاز", 403)

    scope = "all"
    cid = None
    if (county_id or "").strip() == "province":
        scope = "province"
        cid = None
    elif (county_id or "").strip():
        scope = "county"
        cid = int(county_id)

    # Province templates are managed only by Secretariat Admin
    if scope == "province" or f.scope == "province":
        require(
            user.role == Role.SECRETARIAT_ADMIN,
            "ایجاد/ویرایش فرم استانی فقط توسط مدیر دبیرخانه امکان‌پذیر است.",
            403,
        )

    try:
        json.loads(schema_text or "{}")
    except Exception:
        return request.app.state.templates.TemplateResponse(
            "forms/edit.html",
            {
                "request": request,
                "form": f,
                "error": "schema_json معتبر نیست.",
                "orgs": db.query(Org).all(),
                "counties": db.query(County).all(),
                "user": user,
                "badge_count": get_badge_count(db, user),
            },
            status_code=400,
        )

    before = {"title": f.title, "scope": f.scope, "county_id": f.county_id, "schema_json": f.schema_json, "org_id": f.org_id}

    f.org_id = org_id
    f.county_id = cid
    f.scope = scope
    f.title = title.strip()
    f.schema_json = schema_text
    add_form_audit_log(
        db,
        actor_id=user.id,
        action="update",
        entity="form_template",
        entity_id=f.id,
        org_id=f.org_id,
        county_id=f.county_id,
        before=before,
        after={"title": f.title, "scope": f.scope, "county_id": f.county_id, "schema_json": f.schema_json, "org_id": f.org_id},
    )

    db.commit()

    return RedirectResponse("/forms", status_code=303)


@router.post("/{form_id}/delete", response_class=HTMLResponse)
def delete_post(request: Request, form_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    # Alias for README compatibility
    return delete(request, form_id, db, user)


@router.delete("/{form_id}", response_class=HTMLResponse)
def delete(request: Request, form_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    require(can_create_form(user))
    f = db.get(FormTemplate, form_id)
    require(f is not None, "فرم یافت نشد", 404)

    if not is_secretariat(user):
        require(f.org_id == user.org_id, "دسترسی غیرمجاز", 403)

    if f.scope == "province":
        require(user.role == Role.SECRETARIAT_ADMIN, "حذف فرم استانی فقط توسط مدیر دبیرخانه امکان‌پذیر است.", 403)

    before = {"title": f.title, "scope": f.scope, "county_id": f.county_id, "schema_json": f.schema_json, "org_id": f.org_id}

    add_form_audit_log(
        db,
        actor_id=user.id,
        action="delete",
        entity="form_template",
        entity_id=f.id,
        org_id=f.org_id,
        county_id=f.county_id,
        before=before,
        after=None,
    )

    db.delete(f)
    db.commit()
    return HTMLResponse("")
