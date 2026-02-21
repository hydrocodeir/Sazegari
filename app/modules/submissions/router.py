from __future__ import annotations

import json
import os
import uuid

from fastapi import APIRouter, Request, Depends, Form, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session
from sqlalchemy import exists, or_

from app.db.session import get_db
from app.core.config import settings
from app.auth.deps import get_current_user
from app.core.rbac import can_submit_data, is_secretariat, is_county, require
from app.db.models.form_template import FormTemplate
from app.db.models.county import County
from app.db.models.user import Role
from app.db.models.submission import Submission
from app.db.models.org_county import OrgCountyUnit
from app.db.models.program_form_type import ProgramFormType
from app.db.models.program_baseline import ProgramBaseline, ProgramBaselineRow
from app.db.models.program_period import ProgramPeriodForm, ProgramPeriodRow
from app.db.models.program_period_year_mode import ProgramPeriodYearMode
from app.utils.schema import parse_schema, validate_payload, build_layout_blueprint
from app.utils.badges import get_badge_count
from app.utils.form_audit import add_form_audit_log

router = APIRouter(prefix="/submissions", tags=["submissions"])

UPLOAD_DIR = settings.UPLOAD_DIR


def _parse_schema(schema_text: str) -> dict:
    return parse_schema(schema_text)


def _require_program_user(user):
    require(
        user
        and user.role
        in (
            Role.ORG_PROV_EXPERT,
            Role.ORG_PROV_MANAGER,
            Role.ORG_COUNTY_EXPERT,
            Role.ORG_COUNTY_MANAGER,
        ),
        "این بخش فقط برای کارشناسان/مدیران استان و شهرستان قابل مشاهده است.",
        403,
    )


def _scope_county_id(user) -> int:
    """Scope key for program monitoring (0=province, >0=county)."""
    if user and user.role in (Role.ORG_COUNTY_EXPERT, Role.ORG_COUNTY_MANAGER):
        require(user.county_id is not None, "برای کاربران شهرستان، شهرستان مشخص نیست.", 400)
        return int(user.county_id)
    return 0


def _validate_period(period_type: str, period_no: int):
    pt = (period_type or "").strip().lower()
    require(pt in ("quarter", "half", "year"), "نوع بازه نامعتبر است.", 400)
    pn = int(period_no)
    if pt == "quarter":
        require(pn in (1, 2, 3, 4), "شماره سه‌ماهه نامعتبر است.", 400)
    elif pt == "half":
        require(pn in (1, 2), "شماره شش‌ماهه نامعتبر است.", 400)
    else:
        require(pn == 1, "برای بازه سالانه، شماره باید 1 باشد.", 400)
    return pt, pn


def _period_label(year: int, period_type: str, period_no: int) -> str:
    q = {1: "اول", 2: "دوم", 3: "سوم", 4: "چهارم"}
    h = {1: "اول", 2: "دوم"}
    pt = (period_type or "").strip().lower()
    if pt == "quarter":
        return f"سه‌ماهه {q.get(period_no, str(period_no))} سال {year}"
    if pt == "half":
        return f"شش‌ماهه {h.get(period_no, str(period_no))} سال {year}"
    if pt == "year":
        return f"سالانه سال {year}"
    return f"بازه {period_no} سال {year}"


def _snapshot_submission(s: Submission) -> dict:
    try:
        payload = json.loads(s.payload_json or "{}")
    except Exception:
        payload = s.payload_json or ""
    return {
        "id": s.id,
        "form_id": s.form_id,
        "org_id": s.org_id,
        "county_id": s.county_id,
        "org_county_unit_id": s.org_county_unit_id,
        "created_by_id": s.created_by_id,
        "payload": payload,
    }


def _snapshot_program_period_form(db: Session, pf: ProgramPeriodForm) -> dict:
    rows = (
        db.query(ProgramPeriodRow)
        .filter(ProgramPeriodRow.period_form_id == pf.id)
        .order_by(ProgramPeriodRow.baseline_row_id.asc(), ProgramPeriodRow.id.asc())
        .all()
    )
    return {
        "id": pf.id,
        "org_id": pf.org_id,
        "county_id": pf.county_id,
        "form_type_id": pf.form_type_id,
        "year": pf.year,
        "period_type": pf.period_type,
        "period_no": pf.period_no,
        "created_by_id": pf.created_by_id,
        "rows": [
            {"baseline_row_id": r.baseline_row_id, "result_value": r.result_value, "actions_text": r.actions_text}
            for r in rows
        ],
    }



def _build_layout_rows(schema: dict) -> tuple[list[dict], list[dict]]:
    """Build render-friendly layout rows from schema.

    Behavior:
      - Layout is defined as rows with 1-3 columns.
      - If schema.layout is missing, a 2-column auto-layout is used.
      - Fields not referenced in schema.layout will be appended at the end as
        full-width single-column rows (in schema.fields order).

    Returns:
      (rows, unplaced_fields)  # unplaced_fields are those not referenced in schema.layout (for UI info)
    """
    fields = schema.get("fields") or []
    if not isinstance(fields, list):
        fields = []

    field_map: dict[str, dict] = {}
    ordered_names: list[str] = []
    for f in fields:
        if isinstance(f, dict) and f.get("name"):
            name = str(f.get("name"))
            ordered_names.append(name)
            field_map[name] = f

    def col_class(columns: int) -> str:
        if columns == 1:
            return "col-12"
        if columns == 3:
            return "col-12 col-md-4"
        return "col-12 col-md-6"

    # Determine fields referenced explicitly in layout (for info)
    explicit = set()
    layout = schema.get("layout")
    if isinstance(layout, list):
        for r in layout:
            if isinstance(r, dict):
                names = r.get("fields") or []
                if isinstance(names, list):
                    for n in names:
                        if n:
                            explicit.add(str(n))

    blueprint = build_layout_blueprint(schema)

    rows: list[dict] = []
    for r in blueprint:
        cols = int(r.get("columns") or 2)
        cols = 1 if cols < 1 else (3 if cols > 3 else cols)
        names = r.get("fields") or []
        if not isinstance(names, list):
            names = []
        names = (names[:cols] + [""] * cols)[:cols]
        cells = []
        for n in names:
            fdef = field_map.get(str(n)) if n else None
            cells.append({"field": fdef, "col_class": col_class(cols)})
        rows.append({"columns": cols, "cells": cells})

    # fields not explicitly placed (informational only)
    unplaced = [field_map[n] for n in ordered_names if n and n not in explicit]
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
    db.flush()

    add_form_audit_log(
        db,
        actor_id=user.id,
        action="create",
        entity="submission",
        entity_id=s.id,
        org_id=s.org_id,
        county_id=s.county_id,
        before=None,
        after=_snapshot_submission(s),
    )

    db.commit()
    db.refresh(s)

    return RedirectResponse(f"/submissions/{s.id}", status_code=303)


# -----------------------------------------------------------------------------
# Program monitoring data entry (periodic: quarter/half/year)
# -----------------------------------------------------------------------------


def _safe_float(v: str | None):
    if v is None:
        return None
    s = str(v).strip()
    if s == "":
        return None
    try:
        return float(s)
    except Exception:
        return None


@router.get("/program", response_class=HTMLResponse)
def program_select_page(request: Request, db: Session = Depends(get_db), user=Depends(get_current_user)):
    require(can_submit_data(user))
    _require_program_user(user)

    scope_county_id = _scope_county_id(user)

    types = (
        db.query(ProgramFormType)
        .filter(ProgramFormType.org_id == user.org_id)
        .order_by(ProgramFormType.title.asc())
        .all()
    )

    # History of previously saved period forms for this user's scope (province or their county)
    # We only show records that contain at least one non-empty row (to avoid clutter from auto-created empty forms).
    non_empty_row_exists = exists().where(
        (ProgramPeriodRow.period_form_id == ProgramPeriodForm.id)
        & (or_(ProgramPeriodRow.result_value.is_not(None), ProgramPeriodRow.actions_text != ""))
    )

    history_forms = (
        db.query(ProgramPeriodForm)
        .filter(
            ProgramPeriodForm.org_id == user.org_id,
            ProgramPeriodForm.county_id == scope_county_id,
            non_empty_row_exists,
        )
        .order_by(ProgramPeriodForm.year.desc(), ProgramPeriodForm.id.desc())
        .limit(200)
        .all()
    )

    type_title_by_id = {t.id: t.title for t in types}
    history = [
        {
            "id": pf.id,
            "type_id": pf.form_type_id,
            "type_title": type_title_by_id.get(pf.form_type_id, "-"),
            "year": pf.year,
            "period_type": pf.period_type,
            "period_no": pf.period_no,
            "period_label": _period_label(pf.year, pf.period_type, pf.period_no),
        }
        for pf in history_forms
    ]

    return request.app.state.templates.TemplateResponse(
        "submissions/program_select.html",
        {
            "request": request,
            "user": user,
            "badge_count": get_badge_count(db, user),
            "types": types,
            "history": history,
            "scope_county_id": scope_county_id,
        },
    )


@router.get("/program/entry", response_class=HTMLResponse)
def program_entry_page(
    request: Request,
    type_id: int,
    year: int,
    period_type: str,
    period_no: int,
    saved: int = 0,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    require(can_submit_data(user))
    _require_program_user(user)

    scope_county_id = _scope_county_id(user)

    pt, pn = _validate_period(period_type, period_no)
    t = db.get(ProgramFormType, int(type_id))
    require(t is not None and t.org_id == user.org_id, "تیپ فرم یافت نشد.", 404)

    baseline = (
        db.query(ProgramBaseline)
        .filter(ProgramBaseline.org_id == user.org_id, ProgramBaseline.form_type_id == t.id)
        .first()
    )
    require(baseline is not None, "ابتدا فرم اولیه/هدف برنامه پایش را تکمیل کنید.", 400)

    baseline_rows = (
        db.query(ProgramBaselineRow)
        .filter(ProgramBaselineRow.baseline_id == baseline.id)
        .order_by(ProgramBaselineRow.row_no.asc(), ProgramBaselineRow.id.asc())
        .all()
    )
    require(len(baseline_rows) > 0, "ابتدا ردیف‌های فرم اولیه را ثبت کنید.", 400)

    # Enforce year mode lock (if already set)
    ym = (
        db.query(ProgramPeriodYearMode)
        .filter(
            ProgramPeriodYearMode.org_id == user.org_id,
            ProgramPeriodYearMode.county_id == scope_county_id,
            ProgramPeriodYearMode.form_type_id == t.id,
            ProgramPeriodYearMode.year == int(year),
        )
        .first()
    )
    if ym is not None:
        require(ym.period_type == pt, "در این سال قبلاً نوع بازه دیگری ثبت شده است و امکان ثبت ترکیبی وجود ندارد.", 400)

    pf = (
        db.query(ProgramPeriodForm)
        .filter(
            ProgramPeriodForm.org_id == user.org_id,
            ProgramPeriodForm.county_id == scope_county_id,
            ProgramPeriodForm.form_type_id == t.id,
            ProgramPeriodForm.year == int(year),
            ProgramPeriodForm.period_type == pt,
            ProgramPeriodForm.period_no == pn,
        )
        .first()
    )
    if pf is None:
        pf = ProgramPeriodForm(
            org_id=user.org_id,
            county_id=scope_county_id,
            form_type_id=t.id,
            year=int(year),
            period_type=pt,
            period_no=pn,
            created_by_id=user.id,
        )
        db.add(pf)
        db.flush()

        add_form_audit_log(
            db,
            actor_id=user.id,
            action="create",
            entity="program_period_form",
            entity_id=pf.id,
            org_id=pf.org_id,
            county_id=pf.county_id,
            before=None,
            after=_snapshot_program_period_form(db, pf),
            comment="ایجاد فرم دوره‌ای پایش برنامه",
        )

        db.commit()
        db.refresh(pf)

    # Ensure per-baseline-row records exist
    existing = db.query(ProgramPeriodRow).filter(ProgramPeriodRow.period_form_id == pf.id).all()
    existing_map = {r.baseline_row_id: r for r in existing}
    created_any = False
    for br in baseline_rows:
        if br.id not in existing_map:
            pr = ProgramPeriodRow(period_form_id=pf.id, baseline_row_id=br.id, result_value=None, actions_text="")
            db.add(pr)
            created_any = True
    if created_any:
        db.commit()

    prows = db.query(ProgramPeriodRow).filter(ProgramPeriodRow.period_form_id == pf.id).all()
    prows_map = {r.baseline_row_id: r for r in prows}

    # Other saved periods for quick navigation (same type + same scope)
    non_empty_row_exists = exists().where(
        (ProgramPeriodRow.period_form_id == ProgramPeriodForm.id)
        & (or_(ProgramPeriodRow.result_value.is_not(None), ProgramPeriodRow.actions_text != ""))
    )
    other_forms = (
        db.query(ProgramPeriodForm)
        .filter(
            ProgramPeriodForm.org_id == user.org_id,
            ProgramPeriodForm.county_id == scope_county_id,
            ProgramPeriodForm.form_type_id == t.id,
            non_empty_row_exists,
        )
        .order_by(ProgramPeriodForm.year.desc(), ProgramPeriodForm.id.desc())
        .limit(100)
        .all()
    )
    history_same_type = [
        {
            "id": x.id,
            "year": x.year,
            "period_type": x.period_type,
            "period_no": x.period_no,
            "period_label": _period_label(x.year, x.period_type, x.period_no),
            "is_current": x.id == pf.id,
        }
        for x in other_forms
    ]

    return request.app.state.templates.TemplateResponse(
        "submissions/program_entry.html",
        {
            "request": request,
            "user": user,
            "badge_count": get_badge_count(db, user),
            "t": t,
            "baseline": baseline,
            "baseline_rows": baseline_rows,
            "pf": pf,
            "prows_map": prows_map,
            "year": int(year),
            "period_type": pt,
            "period_no": pn,
            "period_label": _period_label(int(year), pt, pn),
            "saved": saved,
            "history_same_type": history_same_type,
        },
    )


@router.post("/program/entry", response_class=RedirectResponse)
def program_entry_save(
    request: Request,
    type_id: int = Form(...),
    year: int = Form(...),
    period_type: str = Form(...),
    period_no: int = Form(...),
    row_id: list[int] = Form(...),
    result_value: list[str] = Form(...),
    actions_text: list[str] = Form(...),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    require(can_submit_data(user))
    _require_program_user(user)

    scope_county_id = _scope_county_id(user)

    pt, pn = _validate_period(period_type, period_no)
    t = db.get(ProgramFormType, int(type_id))
    require(t is not None and t.org_id == user.org_id, "تیپ فرم یافت نشد.", 404)

    # If year mode exists, enforce it
    ym = (
        db.query(ProgramPeriodYearMode)
        .filter(
            ProgramPeriodYearMode.org_id == user.org_id,
            ProgramPeriodYearMode.county_id == scope_county_id,
            ProgramPeriodYearMode.form_type_id == t.id,
            ProgramPeriodYearMode.year == int(year),
        )
        .first()
    )
    if ym is not None:
        require(ym.period_type == pt, "در این سال قبلاً نوع بازه دیگری ثبت شده است و امکان ثبت ترکیبی وجود ندارد.", 400)

    pf = (
        db.query(ProgramPeriodForm)
        .filter(
            ProgramPeriodForm.org_id == user.org_id,
            ProgramPeriodForm.county_id == scope_county_id,
            ProgramPeriodForm.form_type_id == t.id,
            ProgramPeriodForm.year == int(year),
            ProgramPeriodForm.period_type == pt,
            ProgramPeriodForm.period_no == pn,
        )
        .first()
    )
    require(pf is not None, "فرم دوره‌ای یافت نشد.", 404)

    # Snapshot before changes for audit log
    before = _snapshot_program_period_form(db, pf)

    # Update rows
    for i, br_id in enumerate(row_id):
        rv = _safe_float(result_value[i] if i < len(result_value) else None)
        at = (actions_text[i] if i < len(actions_text) else "") or ""
        pr = (
            db.query(ProgramPeriodRow)
            .filter(ProgramPeriodRow.period_form_id == pf.id, ProgramPeriodRow.baseline_row_id == int(br_id))
            .first()
        )
        if pr is None:
            pr = ProgramPeriodRow(period_form_id=pf.id, baseline_row_id=int(br_id))
        pr.result_value = rv
        pr.actions_text = at.strip()
        db.add(pr)

    # Create year mode lock on first successful save
    if ym is None:
        ym = ProgramPeriodYearMode(
            org_id=user.org_id,
            county_id=scope_county_id,
            form_type_id=t.id,
            year=int(year),
            period_type=pt,
        )
        db.add(ym)

    db.flush()
    after = _snapshot_program_period_form(db, pf)

    add_form_audit_log(
        db,
        actor_id=user.id,
        action="update",
        entity="program_period_form",
        entity_id=pf.id,
        org_id=pf.org_id,
        county_id=pf.county_id,
        before=before,
        after=after,
        comment="ویرایش/ثبت داده فرم دوره‌ای پایش برنامه",
    )

    db.commit()
    return RedirectResponse(
        url=f"/submissions/program/entry?type_id={t.id}&year={int(year)}&period_type={pt}&period_no={pn}&saved=1",
        status_code=303,
    )


@router.post("/program/delete", response_class=RedirectResponse)
def program_period_delete(
    request: Request,
    period_form_id: int = Form(...),
    next_url: str = Form("/submissions/program"),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """Delete a previously saved program monitoring period form (within user's scope)."""
    require(can_submit_data(user))
    _require_program_user(user)

    scope_county_id = _scope_county_id(user)
    pf = db.get(ProgramPeriodForm, int(period_form_id))
    require(pf is not None, "فرم دوره‌ای یافت نشد.", 404)
    require(pf.org_id == user.org_id and pf.county_id == scope_county_id, "دسترسی غیرمجاز", 403)

    form_type_id = pf.form_type_id
    year = pf.year

    before = _snapshot_program_period_form(db, pf)

    db.delete(pf)
    db.flush()

    # If this was the last period for that year+type in this scope, unlock year-mode
    remaining = (
        db.query(ProgramPeriodForm)
        .filter(
            ProgramPeriodForm.org_id == user.org_id,
            ProgramPeriodForm.county_id == scope_county_id,
            ProgramPeriodForm.form_type_id == form_type_id,
            ProgramPeriodForm.year == year,
        )
        .count()
    )
    if remaining == 0:
        ym = (
            db.query(ProgramPeriodYearMode)
            .filter(
                ProgramPeriodYearMode.org_id == user.org_id,
                ProgramPeriodYearMode.county_id == scope_county_id,
                ProgramPeriodYearMode.form_type_id == form_type_id,
                ProgramPeriodYearMode.year == year,
            )
            .first()
        )
        if ym is not None:
            db.delete(ym)

    add_form_audit_log(
        db,
        actor_id=user.id,
        action="delete",
        entity="program_period_form",
        entity_id=pf.id,
        org_id=pf.org_id,
        county_id=pf.county_id,
        before=before,
        after=None,
        comment="حذف فرم دوره‌ای پایش برنامه",
    )

    db.commit()

    # Prevent open redirect: only allow local paths
    if not (next_url or "").startswith("/"):
        next_url = "/submissions/program"
    return RedirectResponse(url=next_url, status_code=303)


# -----------------------------------------------------------------------------
# Single submission view (MUST be defined after /program routes)
# -----------------------------------------------------------------------------


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
