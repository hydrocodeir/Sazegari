from __future__ import annotations

from fastapi import APIRouter, Request, Depends, Form, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_

from app.db.session import get_db
from app.auth.deps import get_current_user
from app.core.rbac import require
from app.db.models.user import Role
from app.utils.badges import get_badge_count

from app.db.models.program_form_type import ProgramFormType
from app.db.models.program_baseline import ProgramBaseline, ProgramBaselineRow
from app.db.models.org import Org
from app.db.models.county import County
from app.db.models.program_period import ProgramPeriodForm, ProgramPeriodRow


router = APIRouter(prefix="/programs", tags=["programs"])


# ----------------------------
# Helpers
# ----------------------------

_Q_NAMES = {1: "اول", 2: "دوم", 3: "سوم", 4: "چهارم"}
_H_NAMES = {1: "اول", 2: "دوم"}


def _require_secretariat_admin(user):
    require(user and user.role == Role.SECRETARIAT_ADMIN, "این بخش فقط برای مدیر دبیرخانه است.", 403)


def _period_label(year: int, period_type: str, period_no: int) -> str:
    pt = (period_type or "").strip().lower()
    if pt == "quarter":
        return f"سه‌ماهه {_Q_NAMES.get(period_no, str(period_no))} سال {year}"
    if pt == "half":
        return f"شش‌ماهه {_H_NAMES.get(period_no, str(period_no))} سال {year}"
    if pt == "year":
        return f"سالانه سال {year}"
    return f"بازه {period_no} سال {year}"


def _fmt_num(v: float | None) -> str:
    if v is None:
        return ""
    # keep integers clean
    if abs(v - int(v)) < 1e-9:
        return str(int(v))
    return f"{v:.2f}".rstrip("0").rstrip(".")


def _safe_float(s: str | None) -> float | None:
    if s is None:
        return None
    s = str(s).strip()
    if s == "":
        return None
    try:
        return float(s)
    except Exception:
        return None


"""This module is reserved for secretariat-admin program monitoring setup.

Data entry and report generation are handled in Submissions and Reports modules.
"""


# ----------------------------
# Pages
# ----------------------------

@router.get("", response_class=HTMLResponse)
def programs_index(
    request: Request,
    org_id: int | None = Query(None),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    _require_secretariat_admin(user)

    orgs = db.query(Org).order_by(Org.name.asc(), Org.id.asc()).all()
    require(len(orgs) > 0, "ابتدا یک سازمان/ارگان تعریف کنید.", 400)

    selected_org_id = int(org_id) if org_id is not None else int(orgs[0].id)
    selected_org = next((o for o in orgs if int(o.id) == selected_org_id), orgs[0])

    types = (
        db.query(ProgramFormType)
        .filter(ProgramFormType.org_id == int(selected_org.id))
        .order_by(ProgramFormType.id.desc())
        .all()
    )

    baseline_by_type = {}
    if types:
        baselines = (
            db.query(ProgramBaseline)
            .filter(ProgramBaseline.org_id == int(selected_org.id), ProgramBaseline.form_type_id.in_([t.id for t in types]))
            .all()
        )
        baseline_by_type = {b.form_type_id: b for b in baselines}

    return request.app.state.templates.TemplateResponse(
        "programs/index.html",
        {
            "request": request,
            "user": user,
            "badge_count": get_badge_count(db, user),
            "orgs": orgs,
            "selected_org": selected_org,
            "types": types,
            "baseline_by_type": baseline_by_type,
        },
    )


@router.post("", response_class=RedirectResponse)
def create_type(
    request: Request,
    org_id: int = Form(...),
    title: str = Form(...),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    _require_secretariat_admin(user)

    title = (title or "").strip()
    require(bool(title), "عنوان تیپ فرم الزامی است.", 400)

    o = db.get(Org, int(org_id))
    require(o is not None, "سازمان انتخاب‌شده معتبر نیست.", 400)

    # مقدمه/نتیجه‌گیری در گزارش‌ها تنظیم می‌شود (نه در تیپ فرم).
    t = ProgramFormType(org_id=int(o.id), title=title, intro_text="", conclusion_text="")
    db.add(t)
    db.commit()
    return RedirectResponse(url=f"/programs?org_id={int(o.id)}", status_code=303)


@router.get("/{type_id}", response_class=HTMLResponse)
def type_page(type_id: int, request: Request, db: Session = Depends(get_db), user=Depends(get_current_user)):
    _require_secretariat_admin(user)
    t = db.get(ProgramFormType, type_id)
    require(t is not None, "تیپ فرم یافت نشد.", 404)

    org = db.get(Org, int(t.org_id))
    require(org is not None, "سازمان یافت نشد.", 404)

    baseline = (
        db.query(ProgramBaseline)
        .filter(ProgramBaseline.org_id == t.org_id, ProgramBaseline.form_type_id == t.id)
        .first()
    )
    rows = []
    if baseline:
        rows = (
            db.query(ProgramBaselineRow)
            .filter(ProgramBaselineRow.baseline_id == baseline.id)
            .order_by(ProgramBaselineRow.row_no.asc())
            .all()
        )

    period_forms = (
        db.query(ProgramPeriodForm)
        .filter(ProgramPeriodForm.org_id == t.org_id, ProgramPeriodForm.form_type_id == t.id)
        .order_by(ProgramPeriodForm.year.desc(), ProgramPeriodForm.period_type.asc(), ProgramPeriodForm.period_no.desc())
        .limit(50)
        .all()
    )

    county_by_id = {}
    c_ids = sorted({int(p.county_id) for p in period_forms if int(p.county_id or 0) != 0})
    if c_ids:
        for c in db.query(County).filter(County.id.in_(c_ids)).all():
            county_by_id[int(c.id)] = c.name

    return request.app.state.templates.TemplateResponse(
        "programs/type.html",
        {
            "request": request,
            "user": user,
            "badge_count": get_badge_count(db, user),
            "t": t,
            "org": org,
            "baseline": baseline,
            "rows": rows,
            "period_forms": period_forms,
            "county_by_id": county_by_id,
            "period_label": _period_label,
            "fmt_num": _fmt_num,
        },
    )


@router.post("/{type_id}/edit", response_class=RedirectResponse)
def edit_type(
    type_id: int,
    request: Request,
    title: str = Form(...),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    _require_secretariat_admin(user)
    t = db.get(ProgramFormType, type_id)
    require(t is not None, "تیپ فرم یافت نشد.", 404)

    title = (title or "").strip()
    require(bool(title), "عنوان تیپ فرم الزامی است.", 400)
    t.title = title
    db.add(t)
    db.commit()
    return RedirectResponse(url=f"/programs/{t.id}", status_code=303)


# ----------------------------
# Baseline CRUD
# ----------------------------

@router.get("/{type_id}/baseline", response_class=HTMLResponse)
def baseline_page(type_id: int, request: Request, db: Session = Depends(get_db), user=Depends(get_current_user)):
    _require_secretariat_admin(user)
    t = db.get(ProgramFormType, type_id)
    require(t is not None, "تیپ فرم یافت نشد.", 404)

    baseline = (
        db.query(ProgramBaseline)
        .filter(ProgramBaseline.org_id == t.org_id, ProgramBaseline.form_type_id == t.id)
        .first()
    )
    if baseline is None:
        baseline = ProgramBaseline(org_id=t.org_id, form_type_id=t.id, created_by_id=user.id)
        db.add(baseline)
        db.commit()
        db.refresh(baseline)

    rows = (
        db.query(ProgramBaselineRow)
        .filter(ProgramBaselineRow.baseline_id == baseline.id)
        .order_by(ProgramBaselineRow.row_no.asc(), ProgramBaselineRow.id.asc())
        .all()
    )

    return request.app.state.templates.TemplateResponse(
        "programs/baseline.html",
        {
            "request": request,
            "user": user,
            "badge_count": get_badge_count(db, user),
            "t": t,
            "baseline": baseline,
            "rows": rows,
        },
    )


@router.post("/{type_id}/baseline/add-row", response_class=RedirectResponse)
def baseline_add_row(
    type_id: int,
    request: Request,
    row_no: int = Form(...),
    title: str = Form(...),
    unit: str = Form(""),
    start_year: int = Form(...),
    end_year: int = Form(...),
    target_value: str = Form(...),
    notes: str = Form(""),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    _require_secretariat_admin(user)
    t = db.get(ProgramFormType, type_id)
    require(t is not None, "تیپ فرم یافت نشد.", 404)

    baseline = (
        db.query(ProgramBaseline)
        .filter(ProgramBaseline.org_id == t.org_id, ProgramBaseline.form_type_id == t.id)
        .first()
    )
    require(baseline is not None, "فرم اولیه ایجاد نشده است.", 400)

    tv = _safe_float(target_value)
    require(tv is not None, "هدف باید عدد باشد.", 400)

    r = ProgramBaselineRow(
        baseline_id=baseline.id,
        row_no=row_no,
        title=(title or "").strip(),
        unit=(unit or "").strip(),
        start_year=start_year,
        end_year=end_year,
        target_value=tv,
        notes=(notes or "").strip(),
    )
    db.add(r)
    db.commit()
    return RedirectResponse(url=f"/programs/{t.id}/baseline", status_code=303)


@router.post("/{type_id}/baseline/row/{row_id}/update", response_class=RedirectResponse)
def baseline_update_row(
    type_id: int,
    row_id: int,
    request: Request,
    row_no: int = Form(...),
    title: str = Form(...),
    unit: str = Form(""),
    start_year: int = Form(...),
    end_year: int = Form(...),
    target_value: str = Form(...),
    notes: str = Form(""),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    _require_secretariat_admin(user)
    t = db.get(ProgramFormType, type_id)
    require(t is not None, "تیپ فرم یافت نشد.", 404)

    r = db.get(ProgramBaselineRow, row_id)
    require(r is not None, "ردیف یافت نشد.", 404)

    baseline = db.get(ProgramBaseline, r.baseline_id)
    require(baseline is not None and baseline.org_id == t.org_id and baseline.form_type_id == t.id, "دسترسی غیرمجاز", 403)

    tv = _safe_float(target_value)
    require(tv is not None, "هدف باید عدد باشد.", 400)

    r.row_no = row_no
    r.title = (title or "").strip()
    r.unit = (unit or "").strip()
    r.start_year = start_year
    r.end_year = end_year
    r.target_value = tv
    r.notes = (notes or "").strip()
    db.add(r)
    db.commit()
    return RedirectResponse(url=f"/programs/{t.id}/baseline", status_code=303)


@router.post("/{type_id}/baseline/row/{row_id}/delete", response_class=RedirectResponse)
def baseline_delete_row(
    type_id: int,
    row_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    _require_secretariat_admin(user)
    t = db.get(ProgramFormType, type_id)
    require(t is not None, "تیپ فرم یافت نشد.", 404)

    r = db.get(ProgramBaselineRow, row_id)
    require(r is not None, "ردیف یافت نشد.", 404)

    baseline = db.get(ProgramBaseline, r.baseline_id)
    require(baseline is not None and baseline.org_id == t.org_id and baseline.form_type_id == t.id, "دسترسی غیرمجاز", 403)

    # Prevent deleting baseline rows that already have period data
    has_p = db.query(ProgramPeriodRow).filter(ProgramPeriodRow.baseline_row_id == r.id).first() is not None
    require(not has_p, "این ردیف در فرم‌های دوره‌ای استفاده شده و قابل حذف نیست.", 400)

    db.delete(r)
    db.commit()
    return RedirectResponse(url=f"/programs/{t.id}/baseline", status_code=303)



# Legacy quarterly endpoints: keep, but redirect users to the unified submissions page
@router.get("/{type_id}/quarterly", response_class=RedirectResponse)
def quarterly_legacy_redirect(type_id: int, request: Request, year: int = Query(...), quarter: int = Query(...)):
    return RedirectResponse(url=f"/submissions/program/entry?type_id={type_id}&year={year}&period_type=quarter&period_no={quarter}", status_code=303)


@router.post("/{type_id}/quarterly", response_class=RedirectResponse)
def quarterly_legacy_post_redirect(type_id: int, request: Request, year: int = Query(...), quarter: int = Query(...)):
    return RedirectResponse(url=f"/submissions/program/entry?type_id={type_id}&year={year}&period_type=quarter&period_no={quarter}", status_code=303)
