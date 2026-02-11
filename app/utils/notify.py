from __future__ import annotations

from sqlalchemy.orm import Session

from app.db.models.notification import Notification
from app.utils.badges import invalidate_badge


def notify(db: Session, user_id: int, message: str, report_id: int | None = None, type: str = "info"):
    """Create an in-app notification (unread).

    Note: Caller should commit the DB session.
    """
    n = Notification(user_id=user_id, report_id=report_id, type=type, message=message, is_read=False)
    db.add(n)
    invalidate_badge(user_id)
