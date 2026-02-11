from __future__ import annotations

from sqlalchemy.orm import Session

from app.db.models.notification import Notification
from app.db.models.user import User
from app.core.redis import get_redis


_BADGE_TTL_SECONDS = 15  # small TTL to reduce DB load while keeping near-realtime UX


def _key(user_id: int) -> str:
    return f"badge:{user_id}"


def get_badge_count(db: Session, user: User) -> int:
    """Unread notification count (cached with Redis TTL if available)."""
    r = get_redis()
    if r is not None:
        try:
            v = r.get(_key(user.id))
            if v is not None:
                return int(v)
        except Exception:
            pass

    cnt = db.query(Notification).filter(Notification.user_id == user.id, Notification.is_read == False).count()

    if r is not None:
        try:
            r.setex(_key(user.id), _BADGE_TTL_SECONDS, int(cnt))
        except Exception:
            pass
    return int(cnt)


def invalidate_badge(user_id: int) -> None:
    r = get_redis()
    if r is None:
        return
    try:
        r.delete(_key(user_id))
    except Exception:
        pass
