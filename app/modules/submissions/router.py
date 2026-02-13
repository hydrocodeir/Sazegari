from __future__ import annotations

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


def _build_layout_rows(schema: dict) -> tuple[list[dict], list[dict]]:
    """Build render-friendly layout rows from schema.

    Returns:
      (rows, unplaced_fields)

    Row shape:
      {"columns": 2, "cells": [{"field": <fdef or None>, "col_class": "col-12 col-md-6"}, ...]}

    Notes:
      - If schema.layout is missing/invalid, we auto-generate a 2-column layout.
      - Fields not placed in layout are returned as unplaced_fields (should still be rendered).
    """
    fields = schema.get("fields") or []
    if not isinstance(fields, list):
        fields = []

    field_map: dict[str, dict] = {}
    for f in fields:
        if isinstance(f, dict) and f.get("name"):
            field_map[str(f.get("name"))] = f

    def col_class(columns: int) -> str:
        if columns == 1:
            return "col-12"
        if columns == 3:
            return "col-12 col-md-4"
        return "col-12 col-md-6"

    layout = schema.get("layout")
    rows: list[dict] = []
    placed: set[str] = set()

    if isinstance(layout, list) and layout:
        for r in layout:
            if not isinstance(r, dict):
                continue
            cols = int(r.get("columns") or 2)
            cols = 1 if cols < 1 else (3 if cols > 3 else cols)
            names = r.get("fields") or []
            if not isinstance(names, list):
                names = []
            names = [str(x) if x is not None else "" for x in names]
            # normalize length
            names = (names[:cols] + [""] * cols)[:cols]
            cells = []
            for n in names:
                fdef = field_map.get(n) if n else None
                if fdef:
                    placed.add(n)
                cells.append({"field": fdef, "col_class": col_class(cols)})
            rows.append({"columns": cols, "cells": cells})

    # fallback: auto layout (2 columns)
    if not rows and fields:
        cols = 2
        for i in range(0, len(fields), cols):
            slice_f = fields[i : i + cols]
            cells = []
            for f in slice_f:
                if isinstance(f, dict) and f.get("name"):
                    placed.add(str(f.get("name")))
                    cells.append({"field": f, "col_class": col_class(cols)})
            # pad to cols
            while len(cells) < cols:
                cells.append({"field": None, "col_class": col_class(cols)})
            rows.append({"columns": cols, "cells": cells})

    unplaced = [f for name, f in field_map.items() if name not in placed]
    return rows, unplaced


@router.get("", response_class=HTMLResponse)
def page(
    request: Request,
    county_id: int | None = None,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """Submission listing.

    Note: We support province-level submissions (county_id = NULL).
    For UI filtering, we use:
      - county_id=0 => فقط استان
      - county_id=<id> => فقط همان شهرستان
      - county_id=None => همه
    """
    require(can_submit_data(user))

    subs: list[Submission] = []
    counties_for_filter: list[County] = []

    if is_county(user):
        # County roles: only their own county submissions
        require(user.org_id is not None and user.county_id is not None, "پروفایل کاربر ناقص است.", 400)
        subs = (
            db.query(Submission)
            .filter(Submission.org_id == user.org_id, Submission.county_id == user.county_id)
            .order_by(Submission.id.desc())
            .limit(200)
            .all()
        )

    elif user.role == Role.ORG_PROV_EXPERT:
        # Provincial expert: submissions of entire org, optionally filtered by county/province
        require(user.org_id is not None, "برای نقش استانی باید ارگان مشخص باشد.", 400)

        q = (
            db.query(Submission)
            .filter(Submission.org_id == user.org_id)
            .order_by(Submission.id.desc())
        )

        if county_id is not None:
            if int(county_id) == 0:
                q = q.filter(Submission.county_id.is_(None))
            else:
                q = q.filter(Submission.county_id == int(county_id))

        subs = q.limit(200).all()

        counties_for_filter = (
            db.query(County)
            .join(OrgCountyUnit, County.id == OrgCountyUnit.county_id)
            .filter(OrgCountyUnit.org_id == user.org_id)
            .order_by(County.name.asc())
            .all()
        )

    else:
        require(False, "دسترسی غیرمجاز", 403)

    # forms list (respect scope rules)
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

    # county name mapping for rendering
    county_name_by_id: dict[int, str] = {c.id: c.name for c in counties_for_filter}
    if is_county(user) and user.county_id and user.county:
        county_name_by_id[user.county_id] = user.county.name

    selected = "" if county_id is None else str(county_id)

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
            "selected_county_id": selected,
            "county_name_by_id": county_name_by_id,
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

    # scope check
    if not is_secretariat(user):
        require(form.org_id == user.org_id, "دسترسی به این فرم ندارید", 403)
        if is_county(user):
            require(form.scope != "province", "دسترسی به این فرم ندارید", 403)
            require((form.scope == "all") or (form.county_id == user.county_id), "دسترسی به این فرم ندارید", 403)

    # Province-scope forms: only provincial expert can fill them
    if form.scope == "province":
        require(user.role == Role.ORG_PROV_EXPERT, "این فرم فقط توسط کارشناس استان قابل تکمیل است.", 403)

    schema = _parse_schema(form.schema_json if form else "{}")
    layout_rows, unplaced_fields = _build_layout_rows(schema)

    counties_for_select: list[County] = []
    # Provincial expert can submit for all counties of their org (except province-scope forms)
    if user.role == Role.ORG_PROV_EXPERT and form.scope != "province":
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
            "layout_rows": layout_rows,
            "unplaced_fields": unplaced_fields,
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

    # Province-scope forms: only provincial expert
    if form.scope == "province":
        require(user.role == Role.ORG_PROV_EXPERT, "این فرم فقط توسط کارشناس استان قابل تکمیل است.", 403)

    schema = _parse_schema(form.schema_json if form else "{}")
    layout_rows, unplaced_fields = _build_layout_rows(schema)

    try:
        payload = json.loads(payload_json or "{}")
    except Exception:
        return request.app.state.templates.TemplateResponse(
            "submissions/new.html",
            {
                "request": request,
                "error": "payload_json معتبر نیست.",
                "form": form,
                "schema": schema,
                "layout_rows": layout_rows,
                "unplaced_fields": unplaced_fields,
                "user": user,
                "badge_count": get_badge_count(db, user),
            },
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
        # NOTE: request.form() returns a Starlette UploadFile instance (FastAPI's UploadFile is a subclass).
        # Avoid isinstance() checks against FastAPI's UploadFile to prevent skipping valid files.
        if getattr(up, "filename", None) and hasattr(up, "read"):
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
            {
                "request": request,
                "error": "\n".join(errors),
                "form": form,
                "schema": schema,
                "layout_rows": layout_rows,
                "unplaced_fields": unplaced_fields,
                "user": user,
                "badge_count": get_badge_count(db, user),
            },
            status_code=400,
        )

    require(user.org_id is not None, "پروفایل کاربر ناقص است.", 400)

    # Province-scope submission: no county and no unit
    if form.scope == "province":
        s = Submission(
            form_id=form_id,
            org_id=user.org_id,
            county_id=None,
            org_county_unit_id=None,
            created_by_id=user.id,
            payload_json=json.dumps(payload, ensure_ascii=False),
        )
        db.add(s)
        db.commit()
        db.refresh(s)
        return RedirectResponse(f"/submissions/{s.id}", status_code=303)

    # Otherwise: resolve target county & unit
    target_county_id = user.county_id
    if user.role == Role.ORG_PROV_EXPERT:
        require(county_id is not None, "شهرستان الزامی است.", 400)
        target_county_id = int(county_id)

    require(target_county_id is not None, "پروفایل کاربر ناقص است.", 400)

    unit = (
        db.query(OrgCountyUnit)
        .filter(OrgCountyUnit.org_id == user.org_id, OrgCountyUnit.county_id == target_county_id)
        .first()
    )
    if not unit:
        return request.app.state.templates.TemplateResponse(
            "submissions/new.html",
            {
                "request": request,
                "error": "واحد ارگان/شهرستان برای این انتخاب تعریف نشده است.",
                "form": form,
                "schema": schema,
                "layout_rows": layout_rows,
                "unplaced_fields": unplaced_fields,
                "user": user,
                "badge_count": get_badge_count(db, user),
            },
            status_code=400,
        )

    s = Submission(
        form_id=form_id,
        org_id=user.org_id,
        county_id=target_county_id,
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

    # Access control
    if is_county(user):
        require(
            user.org_id == s.org_id and user.county_id == s.county_id and s.county_id is not None,
            "دسترسی غیرمجاز",
            403,
        )
    elif user.role == Role.ORG_PROV_EXPERT:
        require(user.org_id == s.org_id, "دسترسی غیرمجاز", 403)
    else:
        require(False, "دسترسی غیرمجاز", 403)

    form = db.get(FormTemplate, s.form_id)
    county = db.get(County, s.county_id) if s.county_id else None
    area_label = county.name if county else "استان"

    return request.app.state.templates.TemplateResponse(
        "submissions/view.html",
        {
            "request": request,
            "sub": s,
            "form": form,
            "county": county,
            "area_label": area_label,
            "user": user,
            "badge_count": get_badge_count(db, user),
        },
    )
