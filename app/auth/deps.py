from fastapi import Request, Depends, HTTPException
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.core.security import verify_session
from app.db.models.user import User

SESSION_COOKIE = "sid"

def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    payload = verify_session(token)
    if not payload or "user_id" not in payload:
        raise HTTPException(status_code=401, detail="Invalid session")
    user = db.get(User, payload["user_id"])
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user
