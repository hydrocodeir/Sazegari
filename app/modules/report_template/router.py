from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from sqlalchemy.orm import Session

from app.auth.deps import get_current_user
from app.core.rbac import require
from app.db.models.user import Role
from app.db.session import get_db
from app.utils.badges import get_badge_count
from app.utils.report_pdf_template import (
    PLACEHOLDERS,
    get_report_pdf_template_html,
    reset_report_pdf_template_html,
    save_report_pdf_template_html,
)


router = APIRouter(tags=["report-template"])


def _require_template_admin(user) -> None:
    require(
        user.role == Role.SECRETARIAT_ADMIN,
        "فقط مدیر دبیرخانه می‌تواند قالب PDF گزارش را مدیریت کند.",
        403,
    )


@router.get("/report-template", response_class=HTMLResponse)
def report_template_page(
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    _require_template_admin(user)
    return request.app.state.templates.TemplateResponse(
        "reports/report_template.html",
        {
            "request": request,
            "user": user,
            "badge_count": get_badge_count(db, user),
            "template_html": get_report_pdf_template_html(),
            "placeholders": PLACEHOLDERS,
        },
    )


@router.post("/report-template")
def save_report_template(
    template_html: str = Form(""),
    user=Depends(get_current_user),
):
    _require_template_admin(user)
    require(bool((template_html or "").strip()), "قالب نمی‌تواند خالی باشد.", 400)
    save_report_pdf_template_html(template_html)
    return RedirectResponse("/report-template", status_code=303)


@router.post("/report-template/reset")
def reset_report_template(user=Depends(get_current_user)):
    _require_template_admin(user)
    reset_report_pdf_template_html()
    return RedirectResponse("/report-template", status_code=303)


@router.get("/report-template/content", response_class=JSONResponse)
def report_template_content(user=Depends(get_current_user)):
    # Any authenticated user can fetch the active template for client-side PDF rendering.
    return {"template_html": get_report_pdf_template_html(), "placeholders": PLACEHOLDERS}
