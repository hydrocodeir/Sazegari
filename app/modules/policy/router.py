from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.auth.deps import get_current_user
from app.core.rbac import ALL_PERMISSIONS, ROLE_PERMISSIONS, has_perm
from app.db.models.user import Role
from app.db.session import get_db
from app.utils.badges import get_badge_count

router = APIRouter(prefix="/policy", tags=["policy"])


ROLE_ORDER: list[Role] = [
    Role.ORG_COUNTY_MANAGER,
    Role.ORG_COUNTY_EXPERT,
    Role.ORG_PROV_MANAGER,
    Role.ORG_PROV_EXPERT,
    Role.SECRETARIAT_USER,
    Role.SECRETARIAT_ADMIN,
]

ROLE_LABELS_FA: dict[Role, str] = {
    Role.ORG_COUNTY_MANAGER: "مدیر شهرستان",
    Role.ORG_COUNTY_EXPERT: "کارشناس شهرستان",
    Role.ORG_PROV_MANAGER: "مدیر استان",
    Role.ORG_PROV_EXPERT: "کارشناس استان",
    Role.SECRETARIAT_USER: "کارشناس دبیرخانه",
    Role.SECRETARIAT_ADMIN: "مدیر دبیرخانه",
}

PERM_LABELS_FA: dict[str, str] = {
    # Forms
    "forms.submit": "ثبت/ارسال اطلاعات (Submission)",
    "forms.template.create": "ایجاد قالب فرم",
    "forms.template.update": "ویرایش قالب فرم",
    "forms.template.delete": "حذف قالب فرم",
    "forms.view_all": "مشاهده همه فرم‌ها",
    "forms.view_org": "مشاهده فرم‌های ارگان",
    "forms.view_county": "مشاهده فرم‌های شهرستان",
    "forms.view_province_scope": "مشاهده فرم‌ها (سطح استان/حوزه)",
    # Masterdata
    "masterdata.manage": "مدیریت داده‌های پایه (MasterData)",
    # Reports
    "reports.create": "ایجاد گزارش",
    "reports.delete": "حذف گزارش",
    "reports.view_all": "مشاهده همه گزارش‌ها",
    "reports.view_org": "مشاهده گزارش‌های ارگان",
    "reports.view_county": "مشاهده گزارش‌های شهرستان",
    "reports.view_queue_own": "مشاهده گزارش‌های صف خود",
    # Workflow
    "workflow.edit_content": "ویرایش محتوا در گردش‌کار",
    "workflow.submit_for_review": "ارسال برای بررسی",
    "workflow.request_revision": "درخواست اصلاح",
    "workflow.approve": "تأیید",
    "workflow.final_approve": "تأیید نهایی",
}

PERM_GROUPS: list[tuple[str, list[str]]] = [
    ("Forms", [
        "forms.submit",
        "forms.template.create",
        "forms.template.update",
        "forms.template.delete",
        "forms.view_all",
        "forms.view_org",
        "forms.view_county",
        "forms.view_province_scope",
    ]),
    ("MasterData", [
        "masterdata.manage",
    ]),
    ("Reports", [
        "reports.create",
        "reports.delete",
        "reports.view_all",
        "reports.view_org",
        "reports.view_county",
        "reports.view_queue_own",
    ]),
    ("Workflow", [
        "workflow.edit_content",
        "workflow.submit_for_review",
        "workflow.request_revision",
        "workflow.approve",
        "workflow.final_approve",
    ]),
]


@router.get("", response_class=HTMLResponse)
def page(request: Request, db: Session = Depends(get_db), user=Depends(get_current_user)):
    roles = [
        {
            "role": r,
            "code": r.value,
            "label": ROLE_LABELS_FA.get(r, r.value),
        }
        for r in ROLE_ORDER
    ]

    # Ensure we only show permissions that exist in RBAC source-of-truth
    perms_set = set(ALL_PERMISSIONS)
    perm_groups = [(g, [p for p in ps if p in perms_set]) for (g, ps) in PERM_GROUPS]

    # Build a matrix: perm -> role_code -> bool
    matrix = {
        perm: {r.value: (perm in ROLE_PERMISSIONS.get(r, set())) for r in ROLE_ORDER}
        for perm in ALL_PERMISSIONS
    }

    return request.app.state.templates.TemplateResponse(
        "policy/index.html",
        {
            "request": request,
            "user": user,
            "badge_count": get_badge_count(db, user),
            "roles": roles,
            "perm_groups": perm_groups,
            "perm_labels": PERM_LABELS_FA,
            "matrix": matrix,
        },
    )
