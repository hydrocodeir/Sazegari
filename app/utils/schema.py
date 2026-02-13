from __future__ import annotations
import json
import re as _re
from datetime import datetime

def parse_schema(schema_text: str) -> dict:
    try:
        s = json.loads(schema_text or "{}")
        return s if isinstance(s, dict) else {}
    except Exception:
        return {}

def _is_empty(val) -> bool:
    return val is None or val == "" or (isinstance(val, list) and len(val) == 0)



def build_layout_blueprint(schema: dict) -> list[dict]:
    """Return a normalized layout blueprint.

    Output: list of rows {"columns": int, "fields": [name_or_empty,...]}.
    Rules:
      - Uses schema.layout if provided (list of rows) else auto 2-col layout.
      - Any field not referenced in layout will be appended at the end as its own row (1 column).
      - Field order for appended rows follows schema.fields order.
    """
    if not isinstance(schema, dict):
        return []

    fields = schema.get("fields") or []
    if not isinstance(fields, list):
        fields = []

    # keep original field order
    field_names: list[str] = []
    for f in fields:
        if isinstance(f, dict) and f.get("name"):
            field_names.append(str(f["name"]))

    def norm_cols(v) -> int:
        try:
            c = int(v)
        except Exception:
            c = 2
        if c < 1:
            c = 1
        if c > 3:
            c = 3
        return c

    rows: list[dict] = []
    placed: set[str] = set()

    layout = schema.get("layout")
    if isinstance(layout, list) and layout:
        for r in layout:
            if not isinstance(r, dict):
                continue
            cols = norm_cols(r.get("columns") or 2)
            names = r.get("fields") or []
            if not isinstance(names, list):
                names = []
            names = [str(x) if x is not None else "" for x in names]
            names = (names[:cols] + [""] * cols)[:cols]
            for n in names:
                if n:
                    placed.add(n)
            rows.append({"columns": cols, "fields": names})

    # fallback: auto 2-col layout
    if not rows and field_names:
        cols = 2
        for i in range(0, len(field_names), cols):
            slice_names = field_names[i : i + cols]
            slice_names = (slice_names[:cols] + [""] * cols)[:cols]
            for n in slice_names:
                if n:
                    placed.add(n)
            rows.append({"columns": cols, "fields": slice_names})

    # append unplaced at end (each as a full-width row)
    for n in field_names:
        if n and n not in placed:
            rows.append({"columns": 1, "fields": [n]})
            placed.add(n)

    return rows


def validate_payload(schema: dict, payload: dict) -> list[str]:
    errors: list[str] = []
    fields = schema.get("fields") or []
    if not isinstance(fields, list):
        return ["ساختار schema معتبر نیست."]

    for f in fields:
        if not isinstance(f, dict):
            continue
        name = f.get("name")
        label = f.get("label") or name
        ftype = (f.get("type") or "text").lower()
        required = bool(f.get("required"))
        regex = f.get("regex") or ""
        options = f.get("options") or []

        if not name:
            continue

        val = payload.get(name)

        if required and _is_empty(val):
            errors.append(f"فیلد «{label}» الزامی است.")
            continue

        if _is_empty(val):
            continue

        if ftype == "number":
            try:
                float(val)
            except Exception:
                errors.append(f"فیلد «{label}» باید عدد باشد.")
        elif ftype == "date":
            if isinstance(val, str):
                try:
                    datetime.strptime(val, "%Y-%m-%d")
                except Exception:
                    errors.append(f"فیلد «{label}» باید تاریخ با فرمت YYYY-MM-DD باشد.")
            else:
                errors.append(f"فیلد «{label}» باید تاریخ باشد.")
        elif ftype == "select":
            if options and val not in options:
                errors.append(f"فیلد «{label}» باید یکی از گزینه‌های تعریف‌شده باشد.")
        elif ftype == "multiselect":
            if not isinstance(val, list):
                errors.append(f"فیلد «{label}» باید لیست باشد.")
            else:
                if options and any(v not in options for v in val):
                    errors.append(f"فیلد «{label}» شامل گزینه نامعتبر است.")
        elif ftype == "file":
            # we store file as dict {"filename":..,"path":..}
            if not isinstance(val, dict) or "path" not in val:
                errors.append(f"فیلد «{label}» فایل معتبر ندارد.")
        # regex validation for text-like fields
        if regex and isinstance(val, str) and ftype in ("text","textarea","select"):
            try:
                if not _re.match(regex, val):
                    errors.append(f"فیلد «{label}» با الگوی معتبر مطابقت ندارد.")
            except Exception:
                errors.append(f"Regex برای «{label}» معتبر نیست.")
    return errors
