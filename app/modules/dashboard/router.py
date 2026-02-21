from __future__ import annotations

from fastapi import APIRouter, Request, Depends, Query
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from sqlalchemy import or_

from app.db.session import get_db
from app.auth.deps import get_current_user
from app.core.rbac import require
from app.db.models.user import Role, User

from app.db.models.submission import Submission
from app.db.models.form_template import FormTemplate
from app.db.models.report import Report
from app.db.models.county import County
from app.db.models.program_form_type import ProgramFormType
from app.db.models.program_baseline import ProgramBaseline
from app.utils.program_report import resolve_latest_period, build_program_report


router = APIRouter(prefix="/dashboard", tags=["dashboard"])


def _require_prov_manager(user: User):
    require(user and user.role == Role.ORG_PROV_MANAGER, "این بخش فقط برای مدیر استان است.", 403)
    require(user.org_id is not None, "برای نقش مدیر استان باید org_id مشخص باشد.", 400)


def _load_tables(db: Session, *, org_id: int, county_id: int | None):
    """Load submissions + reports for provincial manager dashboard.

    county_id semantics (UI):
      - None  => همه
      - 0     => فقط استان (Submission.county_id is NULL, Report.county_id is NULL)
      - >0    => فقط همان شهرستان
    """

    # -------- submissions
    subs_q = db.query(Submission).filter(Submission.org_id == int(org_id)).order_by(Submission.id.desc())
    if county_id is not None:
        if int(county_id) == 0:
            subs_q = subs_q.filter(Submission.county_id.is_(None))
        else:
            subs_q = subs_q.filter(Submission.county_id == int(county_id))
    subs = subs_q.limit(200).all()

    forms_map = {}
    if subs:
        fids = sorted({int(s.form_id) for s in subs})
        if fids:
            forms_map = {f.id: f.title for f in db.query(FormTemplate).filter(FormTemplate.id.in_(fids)).all()}

    # county name lookup
    county_name_by_id = {}
    cids = sorted({int(s.county_id) for s in subs if s.county_id is not None})
    if county_id is not None and int(county_id) > 0:
        cids = sorted(set(cids + [int(county_id)]))
    if cids:
        for c in db.query(County).filter(County.id.in_(cids)).all():
            county_name_by_id[int(c.id)] = c.name

    # -------- reports
    reports_q = db.query(Report).filter(Report.org_id == int(org_id)).order_by(Report.id.desc())
    if county_id is not None:
        if int(county_id) == 0:
            reports_q = reports_q.filter(Report.county_id.is_(None))
        else:
            reports_q = reports_q.filter(Report.county_id == int(county_id))
    reports = reports_q.limit(200).all()

    owner_names = {}
    owner_ids = sorted({int(r.current_owner_id) for r in reports if getattr(r, "current_owner_id", None)})
    if owner_ids:
        owner_names = {
            u.id: (u.full_name or u.username or str(u.id))
            for u in db.query(User).filter(User.id.in_(owner_ids)).all()
        }

    # Enrich county map using reports too
    rcids = sorted({int(r.county_id) for r in reports if r.county_id is not None})
    all_cids = sorted(set(list(county_name_by_id.keys()) + rcids))
    if all_cids:
        for c in db.query(County).filter(County.id.in_(all_cids)).all():
            county_name_by_id[int(c.id)] = c.name

    return {
        "subs": subs,
        "forms_map": forms_map,
        "reports": reports,
        "owner_names": owner_names,
        "county_name_by_id": county_name_by_id,
    }


@router.get("/prov/tables", response_class=HTMLResponse)
def prov_tables(
    request: Request,
    county_id: str | None = Query(None),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    _require_prov_manager(user)

    cid = None
    if county_id is not None:
        s = str(county_id).strip()
        if s != "":
            try:
                cid = int(s)
            except Exception:
                cid = None

    data = _load_tables(db, org_id=int(user.org_id), county_id=cid)
    return request.app.state.templates.TemplateResponse(
        "dashboard/_prov_manager_tables.html",
        {
            "request": request,
            "user": user,
            "selected_county_id": cid,
            **data,
        },
    )


@router.get("/prov/program-charts", response_class=HTMLResponse)
def prov_program_charts(
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    _require_prov_manager(user)

    org_id = int(user.org_id)
    types = (
        db.query(ProgramFormType)
        .filter(ProgramFormType.org_id == org_id)
        .order_by(ProgramFormType.id.desc())
        .all()
    )

    charts: list[dict] = []
    for t in types:
        baseline = (
            db.query(ProgramBaseline)
            .filter(ProgramBaseline.org_id == org_id, ProgramBaseline.form_type_id == int(t.id))
            .first()
        )
        if baseline is None:
            continue

        # Latest entered period for "تجمیع شهرستان‌ها" (کل استان)
        try:
            latest = resolve_latest_period(
                db,
                org_id=org_id,
                form_type_id=int(t.id),
                mode="county_agg",
            )
        except Exception:
            # No data yet for this type
            continue

        try:
            rep = build_program_report(
                db,
                org_id=org_id,
                form_type_id=int(t.id),
                year=int(latest["year"]),
                period_type=str(latest["period_type"]),
                period_no=int(latest["period_no"]),
                mode="county_agg",
            )
        except Exception:
            continue

        rows = []
        max_val = 0.0
        for r in rep.get("rows") or []:
            target = float(r.get("target_value") or 0.0)
            achieved = float(r.get("cumulative") or 0.0)
            max_val = max(max_val, target, achieved)
            rows.append(
                {
                    "row_no": r.get("row_no"),
                    "title": r.get("title") or "",
                    "unit": r.get("unit") or "",
                    "target": target,
                    "achieved": achieved,
                    "target_disp": r.get("target_value_display") or "",
                    "achieved_disp": r.get("cumulative_display") or "",
                    "progress": float(r.get("progress") or 0.0),
                }
            )

        # Pre-compute heights for a simple column chart (CSS based)
        max_px = 180.0
        for r in rows:
            r["target_h"] = (r["target"] / max_val * max_px) if max_val > 0 else 0.0
            r["achieved_h"] = (r["achieved"] / max_val * max_px) if max_val > 0 else 0.0
            r["progress_pct"] = (
                min(100.0, (r["achieved"] / r["target"] * 100.0))
                if r["target"] > 0
                else 0.0
            )

        charts.append(
            {
                "type": {"id": int(t.id), "title": t.title},
                "latest_label": rep.get("current_label") or "",
                "scope_label": rep.get("scope_label") or "",
                "rows": rows,
                "has_data": bool(rows),
            }
        )

    return request.app.state.templates.TemplateResponse(
        "dashboard/_prov_manager_program_charts.html",
        {
            "request": request,
            "user": user,
            "charts": charts,
        },
    )
