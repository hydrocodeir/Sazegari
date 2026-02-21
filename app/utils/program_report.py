from __future__ import annotations

from dataclasses import dataclass
import html
from typing import Literal

from sqlalchemy.orm import Session
from sqlalchemy import and_, or_

from app.core.rbac import require
from app.db.models.program_baseline import ProgramBaseline, ProgramBaselineRow
from app.db.models.program_period import ProgramPeriodForm, ProgramPeriodRow
from app.db.models.program_form_type import ProgramFormType
from app.db.models.county import County


PeriodType = Literal["quarter", "half", "year"]
ScopeMode = Literal["province", "county", "county_agg"]


_Q_NAMES = {1: "اول", 2: "دوم", 3: "سوم", 4: "چهارم"}
_H_NAMES = {1: "اول", 2: "دوم"}


def period_label(year: int, period_type: str, period_no: int) -> str:
    pt = (period_type or "").strip().lower()
    if pt == "quarter":
        # Match the wording used in the sample Excel (e.g., "سه ماه اول سال 1404").
        return f"سه ماه {_Q_NAMES.get(int(period_no), str(period_no))} سال {year}"
    if pt == "half":
        return f"شش ماه {_H_NAMES.get(int(period_no), str(period_no))} سال {year}"
    if pt == "year":
        return f"سال {year}"
    return f"بازه {period_no} سال {year}"


def fmt_num(v: float | None) -> str:
    if v is None:
        return ""
    if abs(v - int(v)) < 1e-9:
        return str(int(v))
    return f"{v:.2f}".rstrip("0").rstrip(".")


def _period_sort_key(year: int, pt: str, pn: int) -> tuple:
    order = {"quarter": 1, "half": 2, "year": 3}
    return (int(year), order.get((pt or "").strip().lower(), 9), int(pn))



def resolve_latest_period(
    db: Session,
    *,
    org_id: int,
    form_type_id: int,
    mode: ScopeMode,
    county_id: int = 0,
) -> dict:
    """Pick the latest period (year/period_type/period_no) that has any entered data.

    This is used for "پایش برنامه (گزارش مقایسه‌ای)" so the user only selects:
    - form_type
    - output scope

    and the system builds the cumulative table based on the latest registered period.
    """

    q = (
        db.query(ProgramPeriodForm.year, ProgramPeriodForm.period_type, ProgramPeriodForm.period_no)
        .join(ProgramPeriodRow, ProgramPeriodRow.period_form_id == ProgramPeriodForm.id)
        .filter(
            ProgramPeriodForm.org_id == org_id,
            ProgramPeriodForm.form_type_id == form_type_id,
            or_(
                ProgramPeriodRow.result_value.isnot(None),
                and_(ProgramPeriodRow.actions_text.isnot(None), ProgramPeriodRow.actions_text != ""),
            ),
        )
        .distinct()
    )

    if mode == "province":
        q = q.filter(ProgramPeriodForm.county_id == 0)
    elif mode == "county":
        q = q.filter(ProgramPeriodForm.county_id == int(county_id))
    else:
        q = q.filter(ProgramPeriodForm.county_id != 0)

    rows = [(int(y), (pt or "").strip().lower(), int(pn or 1)) for (y, pt, pn) in q.all()]
    rows = [r for r in rows if r[1] in ("quarter", "half", "year")]
    require(rows, "برای این تیپ فرم هنوز داده‌ای ثبت نشده است.", 400)

    def sort_key(r: tuple[int, str, int]) -> tuple[int, int, int, int]:
        y, pt, pn = r
        end_month = 12
        if pt == "quarter":
            end_month = pn * 3
        elif pt == "half":
            end_month = pn * 6
        elif pt == "year":
            end_month = 12
        type_priority = {"quarter": 3, "half": 2, "year": 1}.get(pt, 0)
        return (y, end_month, type_priority, pn)

    y, pt, pn = max(rows, key=sort_key)
    return {"year": int(y), "period_type": str(pt), "period_no": int(pn)}

def build_program_report(
    db: Session,
    *,
    org_id: int,
    form_type_id: int,
    year: int,
    period_type: str,
    period_no: int,
    mode: ScopeMode,
    county_id: int = 0,
) -> dict:
    """Build program monitoring report data.

    - Annual columns are shown ONLY for years that have any entered data in the included timeframe.
    - Missing values: display blank, but calculations treat as 0.
    - mode:
        - province: only province-scope data (county_id = 0)
        - county: only the given county_id
        - county_agg: aggregate all county-scope data (county_id > 0)
    """

    pt = (period_type or "").strip().lower()
    require(pt in ("quarter", "half", "year"), "نوع بازه نامعتبر است.", 400)
    year = int(year)
    pn = int(period_no)

    t = db.get(ProgramFormType, form_type_id)
    require(t is not None and t.org_id == org_id, "تیپ فرم نامعتبر است.", 400)

    baseline = (
        db.query(ProgramBaseline)
        .filter(and_(ProgramBaseline.org_id == org_id, ProgramBaseline.form_type_id == form_type_id))
        .first()
    )
    require(baseline is not None, "برای این تیپ فرم هنوز برنامه پایش ثبت نشده است.", 400)

    baseline_rows = (
        db.query(ProgramBaselineRow)
        .filter(ProgramBaselineRow.baseline_id == baseline.id)
        .order_by(ProgramBaselineRow.row_no.asc())
        .all()
    )

    # Validate that at least one period form exists for the selected period (for selected scope)
    pf_q = db.query(ProgramPeriodForm.id).filter(
        ProgramPeriodForm.org_id == org_id,
        ProgramPeriodForm.form_type_id == form_type_id,
        ProgramPeriodForm.year == year,
        ProgramPeriodForm.period_type == pt,
        ProgramPeriodForm.period_no == pn,
    )
    if mode == "province":
        pf_q = pf_q.filter(ProgramPeriodForm.county_id == 0)
    elif mode == "county":
        pf_q = pf_q.filter(ProgramPeriodForm.county_id == int(county_id))
    else:
        pf_q = pf_q.filter(ProgramPeriodForm.county_id != 0)
    require(pf_q.first() is not None, "برای بازه انتخاب‌شده هنوز داده‌ای ثبت نشده است.", 400)

    # Load all period rows (for annual/actions/cumulative) for this type.
    q = (
        db.query(
            ProgramPeriodRow,
            ProgramPeriodForm.year,
            ProgramPeriodForm.period_type,
            ProgramPeriodForm.period_no,
            ProgramPeriodForm.county_id,
        )
        .join(ProgramPeriodForm, ProgramPeriodRow.period_form_id == ProgramPeriodForm.id)
        .filter(
            ProgramPeriodForm.org_id == org_id,
            ProgramPeriodForm.form_type_id == form_type_id,
        )
    )

    if mode == "province":
        q = q.filter(ProgramPeriodForm.county_id == 0)
    elif mode == "county":
        q = q.filter(ProgramPeriodForm.county_id == int(county_id))
    else:
        q = q.filter(ProgramPeriodForm.county_id != 0)

    p_rows = q.all()

    county_name_by_id: dict[int, str] = {}
    if mode == "county_agg":
        ids = sorted({int(c_id) for (_pr, _y, _pt, _pn, c_id) in p_rows if int(c_id) != 0})
        if ids:
            for c in db.query(County).filter(County.id.in_(ids)).all():
                county_name_by_id[int(c.id)] = c.name

    # Human-readable scope label for titles
    scope_label = "استان"
    if mode == "county_agg":
        scope_label = "تجمیع شهرستان‌ها"
    elif mode == "county":
        c = db.get(County, int(county_id)) if int(county_id) else None
        scope_label = f"شهرستان {getattr(c, 'name', county_id)}"

    def include_for_annual(target_year: int, row_pt: str, row_pn: int) -> bool:
        if int(target_year) < year:
            return True
        if int(target_year) > year:
            return False
        # current year: only include prior periods of the selected period_type
        if (row_pt or "").strip().lower() != pt:
            return False
        return int(row_pn) < pn

    def include_for_actions(target_year: int, row_pt: str, row_pn: int) -> bool:
        if int(target_year) < year:
            return True
        if int(target_year) > year:
            return False
        if (row_pt or "").strip().lower() != pt:
            return False
        return int(row_pn) <= pn

    # Determine which annual columns should be visible.
    # Requirement: show annual columns only for past years (exclude current year).
    years_with_data: set[int] = set()
    for pr, y, _pt, _pn, _c_id in p_rows:
        y = int(y)
        if y < year and pr.result_value is not None:
            years_with_data.add(y)

    year_cols = sorted(years_with_data)
    current_label = period_label(year, pt, pn)

    # For the latest registered year, show all periods up to the selected one (ONLY within that year).
    # This fixes cases like: selected = "سه ماه دوم" but "سه ماه اول" must still be included in totals.
    if pt == "quarter":
        current_period_nos = list(range(1, pn + 1))
    elif pt == "half":
        current_period_nos = list(range(1, pn + 1))
    else:
        current_period_nos = [1]

    current_cols: list[dict] = []
    for i in current_period_nos:
        if pt == "year":
            lbl = f"عملکرد سال {year}"
        else:
            lbl = period_label(year, pt, i)
        current_cols.append({"period_no": int(i), "label": lbl})

    # Prepare current-year period rows for quick access
    current_by_baseline_period: dict[tuple[int, int], list[ProgramPeriodRow]] = {}
    for pr, y, r_pt, r_pn, _c_id in p_rows:
        if int(y) == year and (r_pt or "").strip().lower() == pt and int(r_pn) in current_period_nos:
            key = (int(pr.baseline_row_id), int(r_pn))
            current_by_baseline_period.setdefault(key, []).append(pr)

    # Aggregate row data
    rows_out: list[dict] = []
    # Group all rows by baseline row for faster summing
    by_baseline: dict[int, list[tuple[ProgramPeriodRow, int, str, int, int]]] = {}
    for pr, y, r_pt, r_pn, c_id in p_rows:
        by_baseline.setdefault(int(pr.baseline_row_id), []).append((pr, int(y), (r_pt or "").strip().lower(), int(r_pn), int(c_id)))

    for br in baseline_rows:
        entries = by_baseline.get(int(br.id), [])

        # annual sums
        annual: dict[int, str] = {}
        annual_calc_sum: float = 0.0
        for y in year_cols:
            s = 0.0
            has_any = False
            for pr, ry, r_pt, r_pn, _c_id in entries:
                if ry == int(y) and include_for_annual(ry, r_pt, r_pn):
                    if pr.result_value is not None:
                        has_any = True
                        s += float(pr.result_value)
            if has_any:
                annual[y] = fmt_num(s)
            else:
                annual[y] = ""
            annual_calc_sum += s

        # current year period results (only for the latest year; show all periods up to the selected one)
        period_values: list[str] = []
        current_year_sum = 0.0
        last_display = ""
        for i in current_period_nos:
            plist = current_by_baseline_period.get((int(br.id), int(i)), [])
            has_any = any(pr.result_value is not None for pr in plist)
            s = sum(float(pr.result_value or 0.0) for pr in plist)
            current_year_sum += s
            disp = fmt_num(s) if has_any else ""
            period_values.append(disp)
            if int(i) == pn:
                last_display = disp

        # Backward-compatible: keep a single 'current' value for templates/exports that still expect it.
        curr_display = last_display

        # actions aggregation
        action_items: list[str] = []
        for pr, ry, r_pt, r_pn, c_id in sorted(entries, key=lambda e: _period_sort_key(e[1], e[2], e[3])):
            if not include_for_actions(ry, r_pt, r_pn):
                continue
            txt = ' '.join((pr.actions_text or '').split())
            if not txt:
                continue
            prefix = period_label(ry, r_pt, r_pn)
            if mode == "county_agg":
                cname = county_name_by_id.get(int(c_id), str(c_id))
                prefix = f"[{cname}] {prefix}"
            action_items.append(f"{prefix}: {txt}")
        actions_agg = "<br>".join(html.escape(x) for x in action_items)

        cumulative = annual_calc_sum + current_year_sum
        target = float(br.target_value or 0.0)
        progress = (cumulative / target) if target > 0 else 0.0

        rows_out.append(
            {
                "row_no": br.row_no,
                "title": br.title,
                "unit": br.unit,
                "start_year": br.start_year,
                "end_year": br.end_year,
                "target_value": float(br.target_value or 0.0),
                "target_value_display": fmt_num(float(br.target_value or 0.0)),
                "annual": annual,
                "current": curr_display,
                "current_values": period_values,
                "actions": actions_agg,
                "cumulative": cumulative,
                "cumulative_display": fmt_num(cumulative),
                "progress": progress,
            }
        )


    # Header label for the target column (Excel sample shows "هدف تا 1405")
    end_years = {int(br.end_year) for br in baseline_rows if getattr(br, "end_year", None)}
    target_header = "هدف تا سال پیش‌بینی خاتمه"
    if len(end_years) == 1:
        target_header = f"هدف تا {next(iter(end_years))}"

    current_perf_label = f"عملکرد {current_label}"

    return {
        "form_type": {"id": t.id, "title": t.title},
        "mode": mode,
        "scope_label": scope_label,
        "year": year,
        "period_type": pt,
        "period_no": pn,
        "current_label": current_label,
        "current_cols": current_cols,
        "current_perf_label": current_perf_label,
        "target_header": target_header,
        # for templates
        "year_cols": year_cols,
        # backward compatibility
        "years": year_cols,
        "rows": rows_out,
    }
