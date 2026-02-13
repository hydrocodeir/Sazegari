from __future__ import annotations
import json
from sqlalchemy.orm import Session
from app.db.models.report_submission import ReportSubmission
from app.db.models.submission import Submission
from app.db.models.form_template import FormTemplate
from app.utils.schema import parse_schema, build_layout_blueprint

def _label_map(schema_json: str) -> dict[str, str]:
    try:
        s = json.loads(schema_json or "{}")
    except Exception:
        return {}
    fields = s.get("fields") if isinstance(s, dict) else []
    if not isinstance(fields, list):
        return {}
    out = {}
    for f in fields:
        if isinstance(f, dict) and f.get("name"):
            out[str(f["name"])] = str(f.get("label") or f["name"])
    return out


def _schema_obj(schema_json: str) -> dict:
    s = parse_schema(schema_json or "{}")
    return s if isinstance(s, dict) else {}

def _field_map(schema: dict) -> dict[str, dict]:
    fields = schema.get("fields") if isinstance(schema, dict) else []
    if not isinstance(fields, list):
        return {}
    out = {}
    for f in fields:
        if isinstance(f, dict) and f.get("name"):
            name = str(f["name"])
            out[name] = {
                "name": name,
                "label": str(f.get("label") or name),
                "type": str(f.get("type") or "text").lower(),
            }
    return out

def aggregate_content(db: Session, report_id: int) -> dict:
    links = db.query(ReportSubmission).filter(ReportSubmission.report_id == report_id).all()
    sub_ids = [l.submission_id for l in links]
    if not sub_ids:
        return {"submissions": [], "by_form": {}, "forms": {}}

    subs = db.query(Submission).filter(Submission.id.in_(sub_ids)).all()
    form_ids = list({s.form_id for s in subs})
    forms = {f.id: f for f in db.query(FormTemplate).filter(FormTemplate.id.in_(form_ids)).all()}

    # form meta (title + labels + layout)
    forms_meta = {}
    for fid, f in forms.items():
        schema = _schema_obj(f.schema_json)
        forms_meta[str(fid)] = {
            "title": f.title,
            "labels": _label_map(f.schema_json),
            "layout": build_layout_blueprint(schema),
            "fields": _field_map(schema),
        }

    submissions_out = []
    by_form: dict[str, list] = {}
    for s in subs:
        try:
            payload = json.loads(s.payload_json or "{}")
        except Exception:
            payload = {}
        title = forms.get(s.form_id).title if forms.get(s.form_id) else f"form#{s.form_id}"
        item = {"id": s.id, "form_id": s.form_id, "form_title": title, "payload": payload}
        submissions_out.append(item)
        by_form.setdefault(str(s.form_id), []).append(item)

    return {"submissions": submissions_out, "by_form": by_form, "forms": forms_meta}
