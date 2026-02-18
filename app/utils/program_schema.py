from __future__ import annotations

"""Utilities for the *dynamic* Program Monitoring ("پایش برنامه") schema.

This module centralizes schema parsing + normalization so the rest of the
application (Program setup, Submissions entry, and Reports) can rely on a
stable structure.

Schema shape (stored in ProgramFormType.baseline_schema_json):

{
  "version": 1,
  "columns": [
    {
      "key": "title",
      "label": "عنوان",
      "type": "text",
      "required": false,
      "is_target": false,
      "use_for_progress": false,
      "in_baseline": true,
      "in_entry": true,
      "in_report": true
    },
    ...
  ]
}

Notes:
  - "core" columns (row_no, title, unit, start_year, end_year, notes) exist in
    ProgramBaselineRow as DB columns for legacy compatibility. They are still
    optional in the UI; if removed from schema, safe defaults will be used.
  - Targets can be 1..N columns. They are stored in ProgramBaselineRow.targets_json.
"""

import json
from typing import Any


# ----------------------------
# Defaults
# ----------------------------


_CORE_DEFAULTS: dict[str, Any] = {
    "row_no": 0,
    "title": "",
    "unit": "",
    "start_year": 0,
    "end_year": 0,
    "notes": "",
}


def safe_defaults_for_core() -> dict[str, Any]:
    """Safe fallback values for DB-backed core fields.

    When the admin removes core columns from the schema, we still need to
    populate the underlying DB columns with sensible values.
    """

    return dict(_CORE_DEFAULTS)


def _default_schema() -> dict:
    """A reasonable starting schema."""

    return {
        "version": 1,
        "columns": [
            {
                "key": "row_no",
                "label": "ردیف",
                "type": "int",
                "required": False,
                "is_target": False,
                "use_for_progress": False,
                "in_baseline": True,
                "in_entry": True,
                "in_report": True,
            },
            {
                "key": "title",
                "label": "شاخص/موضوع",
                "type": "text",
                "required": True,
                "is_target": False,
                "use_for_progress": False,
                "in_baseline": True,
                "in_entry": True,
                "in_report": True,
            },
            {
                "key": "unit",
                "label": "واحد",
                "type": "text",
                "required": False,
                "is_target": False,
                "use_for_progress": False,
                "in_baseline": True,
                "in_entry": True,
                "in_report": True,
            },
            {
                "key": "start_year",
                "label": "سال شروع",
                "type": "int",
                "required": False,
                "is_target": False,
                "use_for_progress": False,
                "in_baseline": True,
                "in_entry": True,
                "in_report": True,
            },
            {
                "key": "end_year",
                "label": "سال خاتمه",
                "type": "int",
                "required": False,
                "is_target": False,
                "use_for_progress": False,
                "in_baseline": True,
                "in_entry": True,
                "in_report": True,
            },
            {
                "key": "target_1",
                "label": "هدف",
                "type": "number",
                "required": False,
                "is_target": True,
                "use_for_progress": True,
                "in_baseline": True,
                "in_entry": True,
                "in_report": True,
            },
            {
                "key": "notes",
                "label": "توضیحات",
                "type": "textarea",
                "required": False,
                "is_target": False,
                "use_for_progress": False,
                "in_baseline": True,
                "in_entry": True,
                "in_report": True,
            },
        ],
    }


# ----------------------------
# Parsing helpers
# ----------------------------


def parse_json_map(text: str | None) -> dict:
    """Parse a JSON object stored as Text.

    Returns {} on any error.
    """

    if not text:
        return {}
    try:
        v = json.loads(text)
        return v if isinstance(v, dict) else {}
    except Exception:
        return {}


def load_schema(schema_text: str | None) -> dict:
    """Load schema JSON stored in DB.

    If empty/invalid, a default schema will be returned.
    """

    if not schema_text:
        return _default_schema()
    try:
        s = json.loads(schema_text)
        if not isinstance(s, dict):
            return _default_schema()
        # normalize columns on load to keep the rest of the app stable
        s["columns"] = normalize_columns(s)
        if "version" not in s:
            s["version"] = 1
        return s
    except Exception:
        return _default_schema()


def dump_schema(schema: dict) -> str:
    """Serialize schema to JSON for storage/display."""

    try:
        return json.dumps(schema or {}, ensure_ascii=False, indent=2)
    except Exception:
        return json.dumps(_default_schema(), ensure_ascii=False, indent=2)


def _norm_bool(v: Any, default: bool = False) -> bool:
    if v is None:
        return default
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return bool(v)
    s = str(v).strip().lower()
    if s in ("1", "true", "yes", "y", "on"):
        return True
    if s in ("0", "false", "no", "n", "off"):
        return False
    return default


def normalize_columns(schema: dict) -> list[dict]:
    """Return a cleaned list of columns with defaults.

    - Ensures every column has required keys.
    - Ensures unique keys (drops duplicates).
    - Ensures at least one target exists.
    - Ensures exactly one target is use_for_progress (if any target exists).
    """

    if not isinstance(schema, dict):
        schema = {}

    cols = schema.get("columns")
    # Backwards compatibility: allow older names
    if not isinstance(cols, list):
        cols = schema.get("fields")

    if not isinstance(cols, list):
        cols = _default_schema()["columns"]

    out: list[dict] = []
    seen: set[str] = set()

    def norm_type(t: Any) -> str:
        tt = (str(t or "text").strip().lower())
        if tt in ("int", "integer"):
            return "int"
        if tt in ("number", "float", "decimal"):
            return "number"
        if tt in ("textarea", "longtext"):
            return "textarea"
        return "text"

    for c in cols:
        if not isinstance(c, dict):
            continue
        key = (c.get("key") or c.get("name") or "").strip()
        if not key:
            continue
        if key in seen:
            continue
        seen.add(key)

        label = str(c.get("label") or key)
        col = {
            "key": key,
            "label": label,
            "type": norm_type(c.get("type")),
            "required": _norm_bool(c.get("required"), False),
            "is_target": _norm_bool(c.get("is_target"), False),
            "use_for_progress": _norm_bool(c.get("use_for_progress"), False),
            "in_baseline": _norm_bool(c.get("in_baseline"), True),
            "in_entry": _norm_bool(c.get("in_entry"), True),
            "in_report": _norm_bool(c.get("in_report"), True),
        }

        out.append(col)

    # Ensure at least one target
    if not any(c.get("is_target") for c in out):
        out.append(
            {
                "key": "target_1",
                "label": "هدف",
                "type": "number",
                "required": False,
                "is_target": True,
                "use_for_progress": True,
                "in_baseline": True,
                "in_entry": True,
                "in_report": True,
            }
        )

    # Ensure exactly one progress target
    target_cols = [c for c in out if c.get("is_target")]
    if target_cols:
        # If multiple marked, keep first
        marked = [c for c in target_cols if c.get("use_for_progress")]
        if not marked:
            target_cols[0]["use_for_progress"] = True
        elif len(marked) > 1:
            keep = marked[0]["key"]
            for c in target_cols:
                c["use_for_progress"] = (c["key"] == keep)

    return out


def split_columns(schema: dict) -> tuple[list[dict], list[dict]]:
    """Split normalized columns into (meta_cols, target_cols)."""

    cols = normalize_columns(schema)
    meta_cols = [c for c in cols if not c.get("is_target")]
    target_cols = [c for c in cols if c.get("is_target")]
    return meta_cols, target_cols


# ----------------------------
# Form value coercion
# ----------------------------


def coerce_value(raw: Any, typ: str | None) -> Any:
    """Coerce raw form values to the desired type."""

    if raw is None:
        return None
    # FastAPI's form() can return UploadFile etc; keep non-str as-is
    if isinstance(raw, (int, float)):
        return raw
    s = str(raw).strip()
    if s == "":
        return None

    t = (typ or "text").strip().lower()
    if t in ("int", "integer"):
        try:
            return int(float(s))
        except Exception:
            return None
    if t in ("number", "float", "decimal"):
        try:
            return float(s)
        except Exception:
            return None
    # textarea/text
    return s
