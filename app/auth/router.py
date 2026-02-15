from __future__ import annotations

from urllib.parse import urlparse

from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import verify_password, sign_session
from app.db.models.user import User
from app.db.session import get_db

router = APIRouter()


def _safe_next_url(next_url: str | None) -> str:
    if not next_url:
        return "/"

    parsed = urlparse(next_url)
    if parsed.scheme or parsed.netloc:
        return "/"

    path = parsed.path or "/"
    if not path.startswith("/"):
        path = "/" + path.lstrip("/")
    if path.startswith("//"):
        return "/"
    if path in ("/login", "/logout"):
        return "/"

    if parsed.query:
        path = f"{path}?{parsed.query}"
    return path


@router.get("/login")
def login_page(request: Request, next: str = "", redirect_url: str = ""):
    target = _safe_next_url(redirect_url or next)
    return request.app.state.templates.TemplateResponse(
        "auth/login.html",
        {"request": request, "badge_count": 0, "next_url": target},
    )


@router.post("/login")
def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    next_url: str = Form(""),
    redirect_url: str = Form(""),
    db: Session = Depends(get_db),
):
    target_url = _safe_next_url(redirect_url or next_url)
    user = db.query(User).filter(User.username == username).first()
    if not user or not verify_password(password, user.password_hash):
        return request.app.state.templates.TemplateResponse(
            "auth/login.html",
            {"request": request, "error": "نام کاربری یا رمز عبور اشتباه است.", "badge_count": 0, "next_url": target_url},
            status_code=400,
        )

    if hasattr(user, 'is_active') and not user.is_active:
        return request.app.state.templates.TemplateResponse(
            "auth/login.html",
            {"request": request, "error": "این حساب کاربری غیرفعال است.", "badge_count": 0, "next_url": target_url},
            status_code=403,
        )

    sid = sign_session({"user_id": user.id})
    resp = RedirectResponse(target_url or "/", status_code=303)
    resp.set_cookie(
        "sid",
        sid,
        httponly=True,
        samesite=settings.COOKIE_SAMESITE,
        secure=settings.COOKIE_SECURE,
        max_age=settings.SESSION_MAX_AGE_SECONDS,
    )
    return resp


@router.post("/logout")
def logout():
    resp = RedirectResponse("/login", status_code=303)
    resp.delete_cookie("sid")
    return resp
