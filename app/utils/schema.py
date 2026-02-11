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
