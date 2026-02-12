import json
import os
import uuid
from fastapi import APIRouter, Request, Depends, Form, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.core.config import settings
from app.auth.deps import get_current_user
from app.core.rbac import can_submit_data, is_secretariat, is_county, require
from app.db.models.form_template import FormTemplate
from app.db.models.county import County
from app.db.models.user import Role
from app.db.models.submission import Submission
from app.db.models.org_county import OrgCountyUnit
from app.utils.schema import parse_schema, validate_payload
from app.utils.badges import get_badge_count

router = APIRouter(prefix="/submissions", tags=["submissions"])

UPLOAD_DIR = settings.UPLOAD_DIR

def _parse_schema(schema_text: str) -> dict:
    return parse_schema(schema_text)

@router.get("", response_class=HTMLResponse)
def page(
    request: Request,
    county_id: int | None = None,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    # Only roles with forms.submit can access submissions
    require(can_submit_data(user))

    subs = []
    unit_map: dict[int, dict] = {}
    counties_for_filter = []

    if is_county(user):
        # County roles: only their own unit submissions
        require(user.org_id is not None and user.county_id is not None, "پروفایل کاربر ناقص است.", 400)
        unit = db.query(OrgCountyUnit).filter(
            OrgCountyUnit.org_id == user.org_id,
            OrgCountyUnit.county_id == user.county_id,
        ).first()
        require(unit is not None, "واحد ارگان/شهرستان برای این کاربر تعریف نشده است.", 400)
        subs = db.query(Submission).filter(
            Submission.org_county_unit_id == unit.id
        ).order_by(Submission.id.desc()).limit(200).all()
        unit_map[unit.id] = {"county_id": unit.county_id}

    elif user.role == Role.ORG_PROV_EXPERT:
        # Provincial expert: submissions of entire org, optionally filtered by county
        require(user.org_id is not None, "برای نقش استانی باید ارگان مشخص باشد.", 400)

        q = (
            db.query(Submission, OrgCountyUnit)
            .join(OrgCountyUnit, Submission.org_county_unit_id == OrgCountyUnit.id)
            .filter(OrgCountyUnit.org_id == user.org_id)
            .order_by(Submission.id.desc())
        )
        if county_id:
            q = q.filter(OrgCountyUnit.county_id == county_id)

        rows = q.limit(200).all()
        subs = [r[0] for r in rows]
        for _, u in rows:
            unit_map[u.id] = {"county_id": u.county_id}

        # filter dropdown values: only counties of this org
        counties_for_filter = (
            db.query(County)
            .join(OrgCountyUnit, County.id == OrgCountyUnit.county_id)
            .filter(OrgCountyUnit.org_id == user.org_id)
            .order_by(County.name.asc())
            .all()
        )
    else:
        # Other roles should not land here
        require(False, "دسترسی غیرمجاز", 403)

    # forms list (respect existing scope rules)
    qf = db.query(FormTemplate).order_by(FormTemplate.title.asc())
    if not is_secretariat(user):
        qf = qf.filter(FormTemplate.org_id == user.org_id)
        if is_county(user):
            qf = qf.filter(
                (FormTemplate.scope == "all")
                | ((FormTemplate.scope == "county") & (FormTemplate.county_id == user.county_id))
            )
    forms = qf.all()
    forms_map = {f.id: f.title for f in forms}

    # Build county name map (for table rendering)
    county_name_by_id = {c.id: c.name for c in counties_for_filter} if counties_for_filter else {}
    if is_county(user) and user.county:
        county_name_by_id[user.county.id] = user.county.name

    unit_to_county_name = {}
    for unit_id, meta in unit_map.items():
        cid = meta.get("county_id")
        if cid:
            unit_to_county_name[unit_id] = county_name_by_id.get(cid, str(cid))

    return request.app.state.templates.TemplateResponse(
        "submissions/index.html",
        {
            "request": request,
            "subs": subs,
            "forms": forms,
            "forms_map": forms_map,
            "user": user,
            "badge_count": get_badge_count(db, user),
            "counties_for_filter": counties_for_filter,
            "selected_county_id": county_id or "",
            "unit_to_county_name": unit_to_county_name,
        },
    )
@router.get("/new", response_class=HTMLResponse)
def new_page(
    request: Request,
    form_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    require(can_submit_data(user))
    form = db.get(FormTemplate, form_id)
    require(form is not None, "فرم یافت نشد", 404)

    # scope check (same logic as before)
    if not is_secretariat(user):
        require(form.org_id == user.org_id, "دسترسی به این فرم ندارید", 403)
        if is_county(user):
            require(form.scope != "province", "دسترسی به این فرم ندارید", 403)
            require((form.scope == "all") or (form.county_id == user.county_id), "دسترسی به این فرم ندارید", 403)

    schema = _parse_schema(form.schema_json if form else "{}")

    counties_for_select = []
    if user.role == Role.ORG_PROV_EXPERT:
        # provincial expert can submit for all counties of their org
        require(user.org_id is not None, "برای نقش استانی باید ارگان مشخص باشد.", 400)
        counties_for_select = (
            db.query(County)
            .join(OrgCountyUnit, County.id == OrgCountyUnit.county_id)
            .filter(OrgCountyUnit.org_id == user.org_id)
            .order_by(County.name.asc())
            .all()
        )

    return request.app.state.templates.TemplateResponse(
        "submissions/new.html",
        {
            "request": request,
            "form": form,
            "schema": schema,
            "user": user,
            "badge_count": get_badge_count(db, user),
            "counties_for_select": counties_for_select,
        },
    )
@router.post("")
async def create(
    request: Request,
    form_id: int = Form(...),
    payload_json: str = Form(...),
    county_id: int | None = Form(None),
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

    # Resolve target unit
    target_county_id = user.county_id
    if user.role == Role.ORG_PROV_EXPERT:
        # provincial expert can submit for any county of their org
        require(user.org_id is not None, "برای نقش استانی باید ارگان مشخص باشد.", 400)
        require(county_id is not None, "شهرستان الزامی است.", 400)
        target_county_id = int(county_id)

    require(user.org_id is not None and target_county_id is not None, "پروفایل کاربر ناقص است.", 400)

    unit = db.query(OrgCountyUnit).filter(
        OrgCountyUnit.org_id == user.org_id,
        OrgCountyUnit.county_id == target_county_id,
    ).first()
    if not unit:
        return request.app.state.templates.TemplateResponse(
            "submissions/new.html",
            {"request": request, "error": "واحد ارگان/شهرستان برای این انتخاب تعریف نشده است.", "form": form, "schema": schema, "user": user, "badge_count": get_badge_count(db, user)},
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
    require(can_submit_data(user))
    s = db.get(Submission, submission_id)
    require(s is not None, "یافت نشد", 404)

    # Access control: user can only view submissions within their allowed scope
    unit = db.get(OrgCountyUnit, s.org_county_unit_id)
    require(unit is not None, "یافت نشد", 404)

    if is_county(user):
        require(user.org_id == unit.org_id and user.county_id == unit.county_id, "دسترسی غیرمجاز", 403)
    elif user.role == Role.ORG_PROV_EXPERT:
        require(user.org_id == unit.org_id, "دسترسی غیرمجاز", 403)
    else:
        require(False, "دسترسی غیرمجاز", 403)

    form = db.get(FormTemplate, s.form_id)
    county = db.get(County, unit.county_id) if unit.county_id else None

    return request.app.state.templates.TemplateResponse(
        "submissions/view.html",
        {"request": request, "sub": s, "form": form, "county": county, "user": user, "badge_count": get_badge_count(db, user)},
    )
