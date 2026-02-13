from __future__ import annotations

import os
import time
import logging

from fastapi import FastAPI, Request, Depends, HTTPException
from fastapi.exception_handlers import http_exception_handler
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.responses import JSONResponse
from starlette.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from app.core.config import settings
from app.core.security import hash_password
from app.db.base import Base
from app.db.session import engine, SessionLocal, get_db
from app.auth.deps import get_current_user
from app.utils.badges import get_badge_count

# Import models to populate SQLAlchemy metadata (needed for create_all)
import app.db.models  # noqa: F401

from app.db.models.user import User, Role
from app.db.models.report import Report
from app.db.models.submission import Submission
from app.db.models.org_county import OrgCountyUnit

from app.auth.router import router as auth_router
from app.modules.orgs.router import router as orgs_router
from app.modules.counties.router import router as counties_router
from app.modules.org_counties.router import router as org_counties_router
from app.modules.forms.router import router as forms_router
from app.modules.users.router import router as users_router
from app.modules.notifications.router import router as notifications_router
from app.modules.policy.router import router as policy_router
from app.modules.submissions.router import router as submissions_router
from app.modules.reports.router import router as reports_router


logger = logging.getLogger("water_compat")


def _is_hx(request: Request) -> bool:
    return (request.headers.get("hx-request") or "").lower() == "true"


def _wants_html(request: Request) -> bool:
    accept = (request.headers.get("accept") or "").lower()
    # HTMX partials are HTML
    if _is_hx(request):
        return True
    # Browser pages
    return ("text/html" in accept) or (accept in ("", "*/*"))


templates = Jinja2Templates(directory="app/templates")
from app.core.rbac import has_perm, Perm, can_manage_masterdata, can_view_forms, can_create_report, can_submit_data

# Make RBAC helpers available in templates
templates.env.globals['has_perm'] = has_perm
templates.env.globals['Perm'] = Perm
templates.env.globals['can_manage_masterdata'] = can_manage_masterdata
templates.env.globals['can_view_forms'] = can_view_forms
templates.env.globals['can_create_report'] = can_create_report
templates.env.globals['can_submit_data'] = can_submit_data

app = FastAPI(title=settings.APP_NAME)
app.state.templates = templates

# CORS (Access-Control-Allow-*) - configurable
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins(),
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=settings.CORS_ALLOW_CREDENTIALS,
)

# Compression for HTML/JSON (helps under load)
app.add_middleware(GZipMiddleware, minimum_size=800)


@app.middleware("http")
async def add_process_time_header(request: Request, call_next):
    start = time.perf_counter()
    resp = await call_next(request)
    resp.headers["X-Process-Time-ms"] = f"{(time.perf_counter() - start) * 1000:.2f}"
    return resp



@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    resp = await call_next(request)
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "SAMEORIGIN"
    resp.headers["Referrer-Policy"] = "same-origin"
    resp.headers["Permissions-Policy"] = "geolocation=(), camera=(), microphone=()"
    return resp

@app.exception_handler(HTTPException)
async def http_exc_handler(request: Request, exc: HTTPException):
    hx = _is_hx(request)

    # 401: redirect to login (works for both normal and HTMX)
    if exc.status_code == 401:
        if hx:
            resp = HTMLResponse("", status_code=401)
            resp.headers["HX-Redirect"] = "/login"
            resp.delete_cookie("sid")
            return resp
        resp = RedirectResponse("/login", status_code=303)
        resp.delete_cookie("sid")
        return resp

    # HTMX: return small inline alert to avoid swapping a full page into a component
    if hx:
        return HTMLResponse(
            f'<div class="alert alert-danger mb-0">خطا ({exc.status_code}): {exc.detail}</div>',
            status_code=exc.status_code,
        )

    if _wants_html(request):
        return templates.TemplateResponse(
            "error.html",
            {"request": request, "status_code": exc.status_code, "detail": exc.detail, "badge_count": 0},
            status_code=exc.status_code,
        )

    return await http_exception_handler(request, exc)



@app.exception_handler(Exception)
async def unhandled_exc_handler(request: Request, exc: Exception):
    hx = _is_hx(request)
    logger.exception("Unhandled exception", exc_info=exc)

    if hx:
        return HTMLResponse(
            '<div class="alert alert-danger mb-0">خطای غیرمنتظره رخ داد.</div>',
            status_code=500,
        )

    if _wants_html(request):
        return templates.TemplateResponse(
            "error.html",
            {"request": request, "status_code": 500, "detail": "خطای غیرمنتظره رخ داد.", "badge_count": 0},
            status_code=500,
        )

    return JSONResponse(status_code=500, content={"detail": "Internal Server Error"})



# Static assets
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# Uploaded files (served as static). Make sure directory exists.
os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=settings.UPLOAD_DIR), name="uploads")

# Routers
app.include_router(auth_router)
app.include_router(orgs_router)
app.include_router(counties_router)
app.include_router(org_counties_router)
app.include_router(forms_router)
app.include_router(users_router)
app.include_router(notifications_router)
app.include_router(policy_router)
app.include_router(submissions_router)
app.include_router(reports_router)


@app.on_event("startup")
def on_startup():
    # DB migrations are handled by the separate "migrate" service.
    return



@app.get("/health", response_class=JSONResponse)
def health():
    return {"status": "ok", "app": settings.APP_NAME}


@app.get("/", response_class=HTMLResponse)
def home(request: Request, db=Depends(get_db), user=Depends(get_current_user)):
    # KPI scope based on role
    reports_q = db.query(Report)
    subs_q = db.query(Submission)

    if user.role.value.startswith("secretariat"):
        pass
    elif user.role.value.startswith("org_prov"):
        reports_q = reports_q.filter(Report.org_id == user.org_id)
        subs_q = subs_q.filter(Submission.org_id == user.org_id)
    else:
        reports_q = reports_q.filter(Report.org_id == user.org_id, Report.county_id == user.county_id)
        subs_q = subs_q.filter(Submission.org_id == user.org_id, Submission.county_id == user.county_id)

    kpi = {
        "unread_notifications": get_badge_count(db, user),
        "my_queue": db.query(Report).filter(Report.current_owner_id == user.id).count(),
        "total_reports": reports_q.count(),
        "total_submissions": subs_q.count(),
    }
    return templates.TemplateResponse(
        "dashboard.html",
        {"request": request, "user": user, "badge_count": kpi["unread_notifications"], "kpi": kpi},
    )
