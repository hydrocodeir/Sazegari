from __future__ import annotations

from fastapi import HTTPException

from app.db.models.user import User, Role

# NOTE: Workflow rules are centralized in app.core.workflow



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
    # طبق نیازمندی جدید:
    # - دبیرخانه (کارشناس/مدیر)
    # - کارشناس ارگان استان
    # امکان ایجاد/ویرایش/حذف «فرم‌تمپلیت» را دارند.
    return is_secretariat(user) or user.role == Role.ORG_PROV_EXPERT


def can_submit_data(user: User) -> bool:
    # شهرستان (کارشناس/مدیر) + کارشناس ارگان استان
    # (برای تکمیل فرم‌های استان و اتصال به گزارش استانی)
    return is_county(user) or user.role == Role.ORG_PROV_EXPERT


def can_create_report(user: User) -> bool:
    """ایجاد گزارش

    طبق نیازمندی:
    - کارشناس شهرستان و کارشناس استان اجازه تولید/ایجاد گزارش را دارند.
    """
    return user.role in (Role.ORG_COUNTY_EXPERT, Role.ORG_PROV_EXPERT)


def can_view_forms(user: User, form_org_id: int, form_county_id: int | None, form_scope: str = "all") -> bool:
    if is_secretariat(user):
        return True
    if user.org_id != form_org_id:
        return False
    # شهرستان فقط فرم‌های عمومی ارگان + شهرستان خودش (و نه فرم‌های استانی)
    if is_county(user):
        if form_scope == "province":
            return False
        if form_scope == "all":
            return True
        return user.county_id == form_county_id
    # استان همه فرم‌های ارگان خود (شامل فرم‌های استانی)
    if is_provincial(user):
        return True
    return False


def can_view_report(user: User, report_org_id: int, report_county_id: int | None, report_owner_id: int | None = None) -> bool:
    if is_secretariat(user):
        return True
    if user.org_id != report_org_id:
        return False
    # شهرستان فقط گزارش شهرستان خودش
    if is_county(user):
        # گزارش استانی county ندارد؛ فقط اگر در صف همان کاربر باشد اجازه مشاهده دارد.
        if report_county_id is None:
            return report_owner_id == user.id
        return user.county_id == report_county_id
    # استان همه شهرستان‌های ارگان خود
    if is_provincial(user):
        return True
    return False


