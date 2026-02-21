from __future__ import annotations

from fastapi import APIRouter, Request, Depends, Query
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.auth.deps import get_current_user
from app.core.rbac import require, is_secretariat, is_county
from app.db.models.form_audit_log import FormAuditLog
from app.db.models.user import User
from app.utils.badges import get_badge_count

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("", response_class=HTMLResponse)
def audit_page(
    request: Request,
    entity: str | None = Query(None),
    action: str | None = Query(None),
    limit: int = Query(200, ge=10, le=1000),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    require(user is not None, "لطفاً وارد شوید.", 401)

    q = db.query(FormAuditLog, User).join(User, User.id == FormAuditLog.actor_id)

    # Scope
    if not is_secretariat(user):
        q = q.filter(FormAuditLog.org_id == user.org_id)
        if is_county(user):
            q = q.filter(FormAuditLog.county_id == user.county_id)
        else:
            # provincial roles see province-scope records (county_id NULL/0)
            q = q.filter((FormAuditLog.county_id == None) | (FormAuditLog.county_id == 0))  # noqa: E711

    if entity:
        q = q.filter(FormAuditLog.entity == entity.strip().lower())
    if action:
        q = q.filter(FormAuditLog.action == action.strip().lower())

    logs = (
        q.order_by(FormAuditLog.created_at.desc(), FormAuditLog.id.desc())
        .limit(int(limit))
        .all()
    )

    # distinct entities for filter UI
    entities = [r[0] for r in db.query(FormAuditLog.entity).distinct().order_by(FormAuditLog.entity.asc()).all()]
    actions = [r[0] for r in db.query(FormAuditLog.action).distinct().order_by(FormAuditLog.action.asc()).all()]

    return request.app.state.templates.TemplateResponse(
        "audit/index.html",
        {
            "request": request,
            "user": user,
            "badge_count": get_badge_count(db, user),
            "logs": logs,
            "entities": entities,
            "actions": actions,
            "selected_entity": (entity or "").strip().lower(),
            "selected_action": (action or "").strip().lower(),
            "limit": int(limit),
        },
    )
