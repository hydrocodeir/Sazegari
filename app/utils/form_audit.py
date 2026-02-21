from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from app.db.models.form_audit_log import FormAuditLog


def _dump(v: Any) -> str:
    if v is None:
        return ""
    try:
        return json.dumps(v, ensure_ascii=False, default=str)
    except Exception:
        try:
            return str(v)
        except Exception:
            return ""


def add_form_audit_log(
    db: Session,
    *,
    actor_id: int,
    action: str,
    entity: str,
    entity_id: int,
    org_id: int | None = None,
    county_id: int | None = None,
    before: Any = None,
    after: Any = None,
    comment: str = "",
):
    """Add a form audit log record to the current transaction."""
    db.add(
        FormAuditLog(
            actor_id=int(actor_id),
            org_id=int(org_id) if org_id is not None else None,
            county_id=int(county_id) if county_id is not None else None,
            action=(action or "").strip().lower(),
            entity=(entity or "").strip().lower(),
            entity_id=int(entity_id),
            before_json=_dump(before),
            after_json=_dump(after),
            comment=(comment or "").strip(),
        )
    )
