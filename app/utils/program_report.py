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
from app.utils.program_schema import load_schema, normalize_columns, split_columns, parse_json_map


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
                # Multi-target mode: consider non-empty results_json as "has data"
                and_(ProgramPeriodRow.results_json.isnot(None), ProgramPeriodRow.results_json != "", ProgramPeriodRow.results_json != "{}"),
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
    """Build program monitoring report data (supports dynamic multi-target columns).

    Key behaviors:
    - Target columns (in_report=True) are treated as "هدف" columns.
    - For each past year that has any entered data, we show a grouped header:
        "عملکرد سال YYYY" with sub-columns for each target (A/B/...)
    - Progress is calculated per target:
        cumulative(target_k) / target_value(target_k)
      where cumulative includes all periods up to the selected period (inclusive).
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

    schema = load_schema(getattr(t, "baseline_schema_json", ""))
    columns = normalize_columns(schema)
    meta_cols, target_cols = split_columns(schema)

    report_meta_cols = [c for c in meta_cols if c.get("in_report")]
    report_target_cols = [c for c in target_cols if c.get("in_report")]
    report_target_keys = [c.get("key") for c in report_target_cols if c.get("key")]

    progress_target_key = None
    for c in report_target_cols:
        if c.get("use_for_progress"):
            progress_target_key = c.get("key")
            break
    if not progress_target_key and report_target_keys:
        progress_target_key = report_target_keys[0]

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
        """Whether a row should be counted in the per-year ("عملکرد سال YYYY") columns.

        Desired behavior (matching the sample tables):
        - Show ALL years that have data up to and including the selected year.
        - For past years (< selected year): include all rows in that year.
        - For the selected year (= selected year): include rows up to the selected period (inclusive)
          and only for the same period_type as the selection (to avoid mixing granularities).
        """

        ty = int(target_year)
        if ty < year:
            return True
        if ty > year:
            return False
        # ty == selected year
        if (row_pt or "").strip().lower() != pt:
            return False
        return int(row_pn) <= pn

    def include_for_actions(target_year: int, row_pt: str, row_pn: int) -> bool:
        # cumulative/actions: include all years < selected year
        if int(target_year) < year:
            return True
        if int(target_year) > year:
            return False
        # current year: include rows up to selected period (inclusive) AND only same period_type
        if (row_pt or "").strip().lower() != pt:
            return False
        return int(row_pn) <= pn

    def numeric_map(pr: ProgramPeriodRow) -> dict[str, float]:
        """Parse results_json and return a numeric map for this row."""
        rmap = parse_json_map(getattr(pr, "results_json", None))
        # Backward compat: if no map but legacy result_value exists, map it to progress_target_key
        if (not rmap) and (pr.result_value is not None) and progress_target_key:
            rmap = {progress_target_key: pr.result_value}
        out: dict[str, float] = {}
        if not rmap:
            return out
        for kk, v in rmap.items():
            try:
                if v is None:
                    continue
                if isinstance(v, (int, float)):
                    out[str(kk)] = float(v)
                    continue
                s = str(v).strip()
                if not s:
                    continue
                out[str(kk)] = float(s)
            except Exception:
                continue
        return out

    def progress_value(pr: ProgramPeriodRow) -> float | None:
        """Legacy single value used by older templates (progress target if possible)."""
        nm = numeric_map(pr)
        if progress_target_key and progress_target_key in nm:
            return nm[progress_target_key]
        if nm:
            # pick first numeric
            return next(iter(nm.values()))
        if pr.result_value is None:
            return None
        try:
            return float(pr.result_value)
        except Exception:
            return None

    # Determine which annual columns should be visible (past years that have any data for any target)
    years_with_data: set[int] = set()
    for pr, y, _ptx, _pnx, _c_id in p_rows:
        y = int(y)
        # include selected year as well (to show the latest entered year's results)
        if y > year:
            continue
        nm = numeric_map(pr)
        if report_target_keys:
            if any(k in nm for k in report_target_keys):
                years_with_data.add(y)
        else:
            if progress_value(pr) is not None:
                years_with_data.add(y)

    year_cols = sorted(years_with_data)
    current_label = period_label(year, pt, pn)

    # Prepare current period rows for quick access (for "عملکرد دوره جاری" if needed in UI/PDF)
    current_by_baseline: dict[int, list[ProgramPeriodRow]] = {}
    for pr, y, r_pt, r_pn, _c_id in p_rows:
        if int(y) == year and (r_pt or "").strip().lower() == pt and int(r_pn) == pn:
            current_by_baseline.setdefault(int(pr.baseline_row_id), []).append(pr)

    # Group all rows by baseline row for faster summing
    by_baseline: dict[int, list[tuple[ProgramPeriodRow, int, str, int, int]]] = {}
    for pr, y, r_pt, r_pn, c_id in p_rows:
        by_baseline.setdefault(int(pr.baseline_row_id), []).append(
            (pr, int(y), (r_pt or "").strip().lower(), int(r_pn), int(c_id))
        )

    # Totals accumulator (numeric only)
    total_targets: dict[str, float] = {k: 0.0 for k in report_target_keys}
    total_cumulative: dict[str, float] = {k: 0.0 for k in report_target_keys}
    total_annual: dict[int, dict[str, float]] = {y: {k: 0.0 for k in report_target_keys} for y in year_cols}

    rows_out: list[dict] = []

    def _try_float(v) -> float | None:
        try:
            if v is None:
                return None
            if isinstance(v, (int, float)):
                return float(v)
            s = str(v).strip()
            if not s:
                return None
            return float(s)
        except Exception:
            return None

    for br in baseline_rows:
        entries = by_baseline.get(int(br.id), [])

        # Annual sums per target (past years only)
        annual_targets: dict[int, dict[str, str]] = {}
        annual_targets_num: dict[int, dict[str, float]] = {}

        for y in year_cols:
            annual_targets[y] = {}
            annual_targets_num[y] = {}
            for k in report_target_keys:
                s = 0.0
                has_any = False
                for pr, ry, r_pt, r_pn, _c_id in entries:
                    if ry == int(y) and include_for_annual(ry, r_pt, r_pn):
                        nm = numeric_map(pr)
                        if k in nm:
                            has_any = True
                            s += float(nm[k])
                annual_targets_num[y][k] = s
                annual_targets[y][k] = fmt_num(s) if has_any else ""

        # Current period multi-target results (only current selected period)
        curr_list = current_by_baseline.get(int(br.id), [])
        curr_targets_sum = {k: 0.0 for k in report_target_keys}
        curr_targets_has = {k: False for k in report_target_keys}
        for pr in curr_list:
            nm = numeric_map(pr)
            for k in report_target_keys:
                if k in nm:
                    curr_targets_sum[k] += float(nm[k])
                    curr_targets_has[k] = True
        curr_targets_out = {k: (fmt_num(curr_targets_sum[k]) if curr_targets_has.get(k) else "") for k in report_target_keys}

        # Cumulative sums per target (all years < selected + current year up to selected period)
        cum_targets_sum = {k: 0.0 for k in report_target_keys}
        cum_targets_has = {k: False for k in report_target_keys}
        for pr, ry, r_pt, r_pn, _c_id in entries:
            if not include_for_actions(ry, r_pt, r_pn):
                continue
            nm = numeric_map(pr)
            for k in report_target_keys:
                if k in nm:
                    cum_targets_sum[k] += float(nm[k])
                    cum_targets_has[k] = True

        # actions aggregation
        action_items: list[str] = []
        for pr, ry, r_pt, r_pn, c_id in sorted(entries, key=lambda e: _period_sort_key(e[1], e[2], e[3])):
            if not include_for_actions(ry, r_pt, r_pn):
                continue
            txt = " ".join((pr.actions_text or "").split())
            if not txt:
                continue
            prefix = period_label(ry, r_pt, r_pn)
            if mode == "county_agg":
                cname = county_name_by_id.get(int(c_id), str(c_id))
                prefix = f"[{cname}] {prefix}"
            action_items.append(f"{prefix}: {txt}")
        actions_agg = "<br>".join(html.escape(x) for x in action_items)

        # Baseline target values per target-key
        targets_map = parse_json_map(getattr(br, "targets_json", "{}"))
        targets_num: dict[str, float] = {}
        for k in report_target_keys:
            v = targets_map.get(k)
            fv = _try_float(v)
            if fv is not None:
                targets_num[k] = fv

        # Progress per target
        progress_targets: dict[str, float | None] = {}
        for k in report_target_keys:
            tv = float(targets_num.get(k) or 0.0)
            if tv > 0 and cum_targets_has.get(k):
                progress_targets[k] = (cum_targets_sum.get(k, 0.0) / tv)
            else:
                progress_targets[k] = None

        # Backward-compat single values
        # Annual (single) = progress target only, past years
        annual_single: dict[int, str] = {}
        for y in year_cols:
            s = 0.0
            has_any = False
            for pr, ry, r_pt, r_pn, _c_id in entries:
                if ry == int(y) and include_for_annual(ry, r_pt, r_pn):
                    pv = progress_value(pr)
                    if pv is not None:
                        has_any = True
                        s += float(pv)
            annual_single[y] = fmt_num(s) if has_any else ""

        # Current (single) = progress target for current period, else legacy sum
        if progress_target_key and progress_target_key in curr_targets_sum and curr_targets_has.get(progress_target_key):
            curr_single_num = float(curr_targets_sum.get(progress_target_key) or 0.0)
            curr_single_has = True
        else:
            curr_single_has = any(pr.result_value is not None for pr in curr_list)
            curr_single_num = sum(float(pr.result_value or 0.0) for pr in curr_list)
        curr_display = fmt_num(curr_single_num) if curr_single_has else ""

        cumulative_single = 0.0
        if progress_target_key and progress_target_key in cum_targets_sum:
            cumulative_single = float(cum_targets_sum.get(progress_target_key) or 0.0)
        else:
            # fallback: sum any numeric
            cumulative_single = sum(float(v) for v in cum_targets_sum.values())

        cumulative_display = fmt_num(cumulative_single)

        prog_single = 0.0
        if progress_target_key and progress_targets.get(progress_target_key) is not None:
            prog_single = float(progress_targets[progress_target_key] or 0.0)

        # Meta fields
        data_map = parse_json_map(getattr(br, "data_json", "{}"))
        meta_out: dict[str, str] = {}
        for c in report_meta_cols:
            k = c["key"]
            if k == "row_no":
                meta_out[k] = str(br.row_no)
            elif k == "title":
                meta_out[k] = br.title or ""
            elif k == "unit":
                meta_out[k] = br.unit or ""
            elif k == "start_year":
                meta_out[k] = str(getattr(br, "start_year", "") or "")
            elif k == "end_year":
                meta_out[k] = str(getattr(br, "end_year", "") or "")
            elif k == "notes":
                meta_out[k] = str(getattr(br, "notes", "") or "")
            else:
                v = data_map.get(k)
                meta_out[k] = "" if v is None else str(v)

        # Target display values (strings)
        targets_out: dict[str, str] = {}
        for c in report_target_cols:
            k = c["key"]
            v = targets_map.get(k)
            if isinstance(v, (int, float)):
                targets_out[k] = fmt_num(float(v))
            else:
                targets_out[k] = "" if v is None else str(v)

        # Update totals
        for y in year_cols:
            for k in report_target_keys:
                total_annual[y][k] += float(annual_targets_num.get(y, {}).get(k, 0.0) or 0.0)

        for k in report_target_keys:
            if k in targets_num:
                total_targets[k] += float(targets_num[k])
            if cum_targets_has.get(k):
                total_cumulative[k] += float(cum_targets_sum.get(k, 0.0) or 0.0)

        rows_out.append(
            {
                "row_no": br.row_no,
                "meta": meta_out,
                "targets": targets_out,
                # multi-target annual map: {year: {target_key: str}}
                "annual_targets": annual_targets,
                # backward compat single annual: {year: str}
                "annual": annual_single,
                # current period:
                "current": curr_display,
                "current_targets": curr_targets_out,
                # cumulative per target numeric + display
                "cumulative_targets": {k: cum_targets_sum.get(k, 0.0) for k in report_target_keys},
                "cumulative_targets_display": {k: (fmt_num(cum_targets_sum.get(k, 0.0)) if cum_targets_has.get(k) else "") for k in report_target_keys},
                "actions": actions_agg,
                "cumulative": cumulative_single,
                "cumulative_display": cumulative_display,
                # progress per target ratio
                "progress_targets": progress_targets,
                # backward compat
                "progress": prog_single,
            }
        )

    # Add a totals row (optional)
    if report_target_keys and rows_out:
        total_meta: dict[str, str] = {c["key"]: "" for c in report_meta_cols}
        if "title" in total_meta:
            total_meta["title"] = "مجموع"
        elif report_meta_cols:
            total_meta[report_meta_cols[0]["key"]] = "مجموع"

        total_targets_out: dict[str, str] = {}
        for c in report_target_cols:
            k = c["key"]
            if k in total_targets and total_targets[k] != 0:
                total_targets_out[k] = fmt_num(total_targets[k])
            else:
                total_targets_out[k] = ""

        total_annual_out: dict[int, dict[str, str]] = {}
        for y in year_cols:
            total_annual_out[y] = {}
            for k in report_target_keys:
                v = float(total_annual.get(y, {}).get(k, 0.0) or 0.0)
                total_annual_out[y][k] = fmt_num(v) if abs(v) > 1e-12 else ""

        total_progress_targets: dict[str, float | None] = {}
        for k in report_target_keys:
            denom = float(total_targets.get(k, 0.0) or 0.0)
            if denom > 0:
                total_progress_targets[k] = float(total_cumulative.get(k, 0.0) or 0.0) / denom
            else:
                total_progress_targets[k] = None

        rows_out.append(
            {
                "is_total": True,
                "meta": total_meta,
                "targets": total_targets_out,
                "annual_targets": total_annual_out,
                "annual": {y: "" for y in year_cols},
                "current": "",
                "current_targets": {k: "" for k in report_target_keys},
                "cumulative_targets": total_cumulative,
                "cumulative_targets_display": {k: (fmt_num(total_cumulative.get(k, 0.0)) if abs(float(total_cumulative.get(k, 0.0) or 0.0)) > 1e-12 else "") for k in report_target_keys},
                "actions": "",
                "cumulative": 0.0,
                "cumulative_display": "",
                "progress_targets": total_progress_targets,
                "progress": 0.0,
            }
        )

    current_perf_label = f"عملکرد {current_label}"

    return {
        "form_type": {"id": t.id, "title": t.title},
        "schema": schema,
        "report_meta_cols": report_meta_cols,
        "report_target_cols": report_target_cols,
        "report_target_keys": report_target_keys,
        "progress_target_key": progress_target_key,
        "mode": mode,
        "scope_label": scope_label,
        "year": year,
        "period_type": pt,
        "period_no": pn,
        "current_label": current_label,
        "current_perf_label": current_perf_label,
        "year_cols": year_cols,
        "years": year_cols,
        "rows": rows_out,
    }

