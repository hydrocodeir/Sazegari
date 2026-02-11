from __future__ import annotations

from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.auth.deps import get_current_user
from app.utils.badges import get_badge_count, invalidate_badge
from app.db.models.notification import Notification
from app.db.models.user import User, Role
from app.core.rbac import is_secretariat, is_provincial, is_county

router = APIRouter(prefix="/notifications", tags=["notifications"])


def _scoped_query(db: Session, user: User):
    """سلسله‌مراتب مشاهده اعلان‌ها:
    - کارشناس‌ها: فقط اعلان‌های خودشان
    - مدیر شهرستان: اعلان‌های تمام کاربران همان ارگان+شهرستان
    - مدیر استان: اعلان‌های تمام کاربران همان ارگان
    - دبیرخانه: همه اعلان‌ها
    """
    q = db.query(Notification)

    if is_secretariat(user):
        return q

    # experts -> only self
    if user.role in (Role.ORG_COUNTY_EXPERT, Role.ORG_PROV_EXPERT):
        return q.filter(Notification.user_id == user.id)

    if user.role == Role.ORG_COUNTY_MANAGER:
        return q.join(User, User.id == Notification.user_id).filter(
            User.org_id == user.org_id,
            User.county_id == user.county_id,
        )

    if user.role == Role.ORG_PROV_MANAGER:
        return q.join(User, User.id == Notification.user_id).filter(User.org_id == user.org_id)

    return q.filter(Notification.user_id == user.id)


@router.get("", response_class=HTMLResponse)
def page(request: Request, db: Session = Depends(get_db), user=Depends(get_current_user)):
    q = _scoped_query(db, user).order_by(Notification.id.desc())
    notes = q.limit(300).all()

    # badge: unread for *this user only*
    unread_personal = get_badge_count(db, user)

    return request.app.state.templates.TemplateResponse(
        "notifications/index.html",
        {
            "request": request,
            "notes": notes,
            "unread": unread_personal,
            "user": user,
            "badge_count": unread_personal,
        },
    )


@router.post("/mark_read")
def mark_read(
    request: Request,
    notification_id: int = Form(...),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    # فقط صاحب اعلان حق خوانده‌شدن دارد
    n = db.get(Notification, notification_id)
    if n and n.user_id == user.id:
        n.is_read = True
        db.commit()
        invalidate_badge(user.id)
    return RedirectResponse("/notifications", status_code=303)


@router.post("/mark_all_read")
def mark_all_read(request: Request, db: Session = Depends(get_db), user=Depends(get_current_user)):
    db.query(Notification).filter(Notification.user_id == user.id, Notification.is_read == False).update(
        {"is_read": True}, synchronize_session=False
    )
    db.commit()
    invalidate_badge(user.id)
    return RedirectResponse("/notifications", status_code=303)
