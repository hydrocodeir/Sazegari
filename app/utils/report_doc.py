from __future__ import annotations
import json

def load_doc(content_json: str | None) -> dict:
    if not content_json:
        return {
            "intro_html": "",
            "conclusion_html": "",
            "meta": {"title": "", "subtitle": ""},
            "sections": [],
            "program_sections": [],
            "aggregation": {"submissions": [], "by_form": {}, "forms": {}},
        }
    try:
        obj = json.loads(content_json)
    except Exception:
        return {
            "intro_html": "",
            "conclusion_html": "",
            "meta": {"title": "", "subtitle": ""},
            "sections": [],
            "program_sections": [],
            "aggregation": {"submissions": [], "by_form": {}, "forms": {}},
        }

    # backward compatibility: if old aggregation dict
    if isinstance(obj, dict) and "submissions" in obj and "aggregation" not in obj:
        return {
            "intro_html": "",
            "conclusion_html": "",
            "meta": {"title": "", "subtitle": ""},
            "sections": [],
            "program_sections": [],
            "aggregation": obj,
        }

    if not isinstance(obj, dict):
        return {
            "intro_html": "",
            "conclusion_html": "",
            "meta": {"title": "", "subtitle": ""},
            "sections": [],
            "program_sections": [],
            "aggregation": {"submissions": [], "by_form": {}, "forms": {}},
        }

    obj.setdefault("intro_html", "")
    obj.setdefault("conclusion_html", "")
    obj.setdefault("meta", {"title": "", "subtitle": ""})
    obj.setdefault("sections", [])
    obj.setdefault("program_sections", [])
    obj.setdefault("aggregation", {"submissions": [], "by_form": {}, "forms": {}})
    if not isinstance(obj.get("meta"), dict):
        obj["meta"] = {"title": "", "subtitle": ""}
    else:
        obj["meta"].setdefault("title", "")
        obj["meta"].setdefault("subtitle", "")

    if not isinstance(obj["sections"], list):
        obj["sections"] = []
    if not isinstance(obj.get("program_sections"), list):
        obj["program_sections"] = []
    if not isinstance(obj["aggregation"], dict):
        obj["aggregation"] = {"submissions": [], "by_form": {}, "forms": {}}
    return obj

def dump_doc(doc: dict) -> str:
    return json.dumps(doc, ensure_ascii=False)
