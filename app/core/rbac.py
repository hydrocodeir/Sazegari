from __future__ import annotations

from fastapi import HTTPException

from app.db.models.user import User, Role
from app.db.models.report import ReportStatus


def require(condition: bool, msg: str = "دسترسی غیرمجاز", status_code: int = 403) -> None:
    """Small helper used across routers.

    Defaults to 403 (permission denied). For validation errors or not-found cases,
    pass `status_code=400/404`.
    """
    if not condition:
        raise HTTPException(status_code=status_code, detail=msg)


def is_secretariat_admin(user: User) -> bool:
    return user.role == Role.SECRETARIAT_ADMIN


def is_secretariat(user: User) -> bool:
    return user.role in (Role.SECRETARIAT_ADMIN, Role.SECRETARIAT_USER)


def is_provincial(user: User) -> bool:
    return user.role in (Role.ORG_PROV_EXPERT, Role.ORG_PROV_MANAGER)


def is_county(user: User) -> bool:
    return user.role in (Role.ORG_COUNTY_EXPERT, Role.ORG_COUNTY_MANAGER)


def can_manage_masterdata(user: User) -> bool:
    return is_secretariat_admin(user)


def can_create_form(user: User) -> bool:
    # Only secretariat (expert+admin) can create/edit/delete forms.
    return is_secretariat(user)


def can_submit_data(user: User) -> bool:
    return is_county(user)


def can_create_report(user: User) -> bool:
    # معمولاً گزارش در شهرستان ساخته می‌شود؛ می‌توان توسعه داد
    return is_county(user)


def can_view_forms(user: User, form_org_id: int, form_county_id: int | None) -> bool:
    if is_secretariat(user):
        return True
    if user.org_id != form_org_id:
        return False
    # شهرستان فقط فرم‌های عمومی ارگان + شهرستان خودش
    if is_county(user):
        return (form_county_id is None) or (user.county_id == form_county_id)
    # استان همه فرم‌های ارگان خود
    if is_provincial(user):
        return True
    return False


def can_view_report(user: User, report_org_id: int, report_county_id: int) -> bool:
    if is_secretariat(user):
        return True
    if user.org_id != report_org_id:
        return False
    # شهرستان فقط گزارش شهرستان خودش
    if is_county(user):
        return user.county_id == report_county_id
    # استان همه شهرستان‌های ارگان خود
    if is_provincial(user):
        return True
    return False


# ---- Workflow rules ----
# action: submit_for_review / approve / request_revision / final_approve


def allowed_actions(user: User, status: ReportStatus) -> list[str]:
    # دبیرخانه
    if is_secretariat(user):
        if status == ReportStatus.SECRETARIAT_REVIEW:
            return ["final_approve", "request_revision"]
        if status == ReportStatus.FINAL_APPROVED:
            return []
        # دبیرخانه فقط مشاهده در سایر مراحل (قابل تغییر)
        return []

    # شهرستان
    if user.role == Role.ORG_COUNTY_EXPERT:
        if status in (ReportStatus.DRAFT, ReportStatus.NEEDS_REVISION):
            return ["submit_for_review"]
        return []
    if user.role == Role.ORG_COUNTY_MANAGER:
        # پشتیبانی از هر دو وضعیت (برای سازگاری با داده‌های قبلی)
        if status in (ReportStatus.COUNTY_MANAGER_REVIEW, ReportStatus.COUNTY_EXPERT_REVIEW):
            return ["approve", "request_revision"]
        return []

    # استان
    if user.role == Role.ORG_PROV_EXPERT:
        if status == ReportStatus.PROV_EXPERT_REVIEW:
            return ["approve", "request_revision"]
        return []
    if user.role == Role.ORG_PROV_MANAGER:
        if status == ReportStatus.PROV_MANAGER_REVIEW:
            return ["approve", "request_revision"]
        return []
    return []


def transition(status: ReportStatus, action: str) -> ReportStatus:
    # مسیر مرحله‌ای
    if action == "submit_for_review":
        # از draft یا needs_revision به مدیر شهرستان
        return ReportStatus.COUNTY_MANAGER_REVIEW

    if action == "approve":
        return {
            ReportStatus.COUNTY_EXPERT_REVIEW: ReportStatus.PROV_EXPERT_REVIEW,
            ReportStatus.COUNTY_MANAGER_REVIEW: ReportStatus.PROV_EXPERT_REVIEW,
            ReportStatus.PROV_EXPERT_REVIEW: ReportStatus.PROV_MANAGER_REVIEW,
            ReportStatus.PROV_MANAGER_REVIEW: ReportStatus.SECRETARIAT_REVIEW,
        }[status]

    if action == "request_revision":
        # بازگشت یک مرحله به عقب (برای اصلاح)
        # - مدیر شهرستان -> کارشناس شهرستان
        # - کارشناس استان ارگان -> مدیر شهرستان
        # - مدیر استان ارگان -> کارشناس استان ارگان
        # - دبیرخانه -> مدیر استان ارگان
        return {
            ReportStatus.COUNTY_MANAGER_REVIEW: ReportStatus.NEEDS_REVISION,
            ReportStatus.PROV_EXPERT_REVIEW: ReportStatus.COUNTY_MANAGER_REVIEW,
            ReportStatus.PROV_MANAGER_REVIEW: ReportStatus.PROV_EXPERT_REVIEW,
            ReportStatus.SECRETARIAT_REVIEW: ReportStatus.PROV_MANAGER_REVIEW,
            # در صورت وجود مرحلهٔ دیگر در برخی داده‌ها
            ReportStatus.COUNTY_EXPERT_REVIEW: ReportStatus.COUNTY_MANAGER_REVIEW,
        }[status]

    if action == "final_approve":
        return ReportStatus.FINAL_APPROVED

    raise KeyError("unknown action")