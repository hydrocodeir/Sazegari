import json
import os
import uuid
from fastapi import APIRouter, Request, Depends, Form, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.core.config import settings
from app.auth.deps import get_current_user
from app.core.rbac import can_submit_data, is_secretariat, is_provincial, is_county, require
from app.db.models.form_template import FormTemplate
from app.db.models.submission import Submission
from app.db.models.org_county import OrgCountyUnit
from app.utils.schema import parse_schema, validate_payload
from app.utils.badges import get_badge_count

router = APIRouter(prefix="/submissions", tags=["submissions"])

UPLOAD_DIR = settings.UPLOAD_DIR

def _parse_schema(schema_text: str) -> dict:
    return parse_schema(schema_text)

@router.get("", response_class=HTMLResponse)
def page(request: Request, db: Session = Depends(get_db), user=Depends(get_current_user)):
    if can_submit_data(user) and user.org_id and user.county_id:
        unit = db.query(OrgCountyUnit).filter(
            OrgCountyUnit.org_id == user.org_id,
            OrgCountyUnit.county_id == user.county_id,
        ).first()
        subs = []
        if unit:
            subs = db.query(Submission).filter(Submission.org_county_unit_id == unit.id).order_by(Submission.id.desc()).all()
    else:
        subs = db.query(Submission).order_by(Submission.id.desc()).limit(200).all()

    qf = db.query(FormTemplate).order_by(FormTemplate.title.asc())
    if not is_secretariat(user):
        qf = qf.filter(FormTemplate.org_id == user.org_id)
        if is_county(user):
            # شهرستان فقط فرم‌های عمومی + شهرستان خودش (و نه فرم‌های استانی)
            qf = qf.filter(
                (FormTemplate.scope == "all")
                | ((FormTemplate.scope == "county") & (FormTemplate.county_id == user.county_id))
            )
    forms = qf.all()
    forms_map = {f.id: f.title for f in forms}
    return request.app.state.templates.TemplateResponse(
        "submissions/index.html",
        {"request": request, "subs": subs, "forms": forms, "forms_map": forms_map, "user": user, "badge_count": get_badge_count(db, user)},
    )

@router.get("/new", response_class=HTMLResponse)
def new_page(request: Request, form_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    require(can_submit_data(user))
    form = db.get(FormTemplate, form_id)
    require(form is not None, "فرم یافت نشد", 404)
    # scope check
    if not is_secretariat(user):
        require(form.org_id == user.org_id, "دسترسی به این فرم ندارید", 403)
        if is_county(user):
            require(form.scope != "province", "دسترسی به این فرم ندارید", 403)
            require((form.scope == "all") or (form.county_id == user.county_id), "دسترسی به این فرم ندارید", 403)
    schema = _parse_schema(form.schema_json if form else "{}")
    return request.app.state.templates.TemplateResponse(
        "submissions/new.html",
        {"request": request, "form": form, "schema": schema, "user": user, "badge_count": get_badge_count(db, user)},
    )

@router.post("")
async def create(
    request: Request,
    form_id: int = Form(...),
    payload_json: str = Form(...),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    require(can_submit_data(user))

    form = db.get(FormTemplate, form_id)
    require(form is not None, "فرم یافت نشد", 404)
    # scope check
    if not is_secretariat(user):
        require(form.org_id == user.org_id, "دسترسی به این فرم ندارید", 403)
        if is_county(user):
            require(form.scope != "province", "دسترسی به این فرم ندارید", 403)
            require((form.scope == "all") or (form.county_id == user.county_id), "دسترسی به این فرم ندارید", 403)
    schema = _parse_schema(form.schema_json if form else "{}")

    try:
        payload = json.loads(payload_json or "{}")
    except Exception:
        return request.app.state.templates.TemplateResponse(
            "submissions/new.html",
            {"request": request, "error": "payload_json معتبر نیست.", "form": form, "schema": schema, "user": user, "badge_count": get_badge_count(db, user)},
            status_code=400,
        )

    # handle file fields: inputs are named file__<fieldname>
    formdata = await request.form()
    for fdef in (schema.get("fields") or []):
        if not isinstance(fdef, dict): 
            continue
        if (fdef.get("type") or "").lower() != "file":
            continue
        name = fdef.get("name")
        if not name:
            continue
        key = f"file__{name}"
        up = formdata.get(key)
        if isinstance(up, UploadFile) and up.filename:
            os.makedirs(UPLOAD_DIR, exist_ok=True)
            ext = os.path.splitext(up.filename)[1]
            fname = f"{uuid.uuid4().hex}{ext}"
            dest = os.path.join(UPLOAD_DIR, fname)
            max_bytes = int(settings.MAX_UPLOAD_MB) * 1024 * 1024
            size = 0
            with open(dest, "wb") as out:
                while True:
                    chunk = await up.read(1024 * 1024)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > max_bytes:
                        # remove partial file
                        try:
                            out.close()
                            os.remove(dest)
                        except Exception:
                            pass
                        require(False, f"فایل معتبر نیست (حداکثر {settings.MAX_UPLOAD_MB}MB).", 400)
                    out.write(chunk)
            payload[name] = {"filename": up.filename, "path": f"uploads/{fname}"}

    errors = validate_payload(schema, payload if isinstance(payload, dict) else {})
    if errors:
        return request.app.state.templates.TemplateResponse(
            "submissions/new.html",
            {"request": request, "error": "\n".join(errors), "form": form, "schema": schema, "user": user, "badge_count": get_badge_count(db, user)},
            status_code=400,
        )

    unit = db.query(OrgCountyUnit).filter(
        OrgCountyUnit.org_id == user.org_id,
        OrgCountyUnit.county_id == user.county_id,
    ).first()
    if not unit:
        return request.app.state.templates.TemplateResponse(
            "submissions/new.html",
            {"request": request, "error": "واحد ارگان/شهرستان برای این کاربر تعریف نشده است.", "form": form, "schema": schema, "user": user, "badge_count": get_badge_count(db, user)},
            status_code=400,
        )

    s = Submission(
        form_id=form_id,
        org_county_unit_id=unit.id,
        created_by_id=user.id,
        payload_json=json.dumps(payload, ensure_ascii=False),
    )
    db.add(s)
    db.commit()
    db.refresh(s)

    return RedirectResponse(f"/submissions/{s.id}", status_code=303)

@router.get("/{submission_id}", response_class=HTMLResponse)
def view(request: Request, submission_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    s = db.get(Submission, submission_id)
    require(s is not None, "یافت نشد", 404)
    form = db.get(FormTemplate, s.form_id)
    return request.app.state.templates.TemplateResponse(
        "submissions/view.html",
        {"request": request, "sub": s, "form": form, "user": user, "badge_count": get_badge_count(db, user)},
    )
