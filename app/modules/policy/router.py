from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.auth.deps import get_current_user
from app.utils.badges import get_badge_count
from app.db.models.user import Role

router = APIRouter(prefix="/policy", tags=["policy"])

@router.get("", response_class=HTMLResponse)
def page(request: Request, db: Session = Depends(get_db), user=Depends(get_current_user)):
    rows = [
        {
            "role": "کارشناس شهرستان",
            "code": Role.ORG_COUNTY_EXPERT.value,
            "forms": "مشاهده فرم‌های ارگان (عمومی + شهرستان خودش) / فقط پرکردن",
            "reports_view": "فقط گزارش‌های ساخته‌شده توسط خودش یا گزارش‌های ارجاع‌شده به خودش",
            "reports_create": "بله (برای شهرستان خودش)",
            "workflow": "ارسال برای مدیر شهرستان",
            "notifications": "فقط اعلان‌های خودش",
            "admin": "خیر",
        },
        {
            "role": "مدیر شهرستان",
            "code": Role.ORG_COUNTY_MANAGER.value,
            "forms": "مشاهده فرم‌های ارگان (عمومی + شهرستان خودش) / فقط پرکردن",
            "reports_view": "همه گزارش‌های ارگان+شهرستان خودش",
            "reports_create": "بله",
            "workflow": "ارسال برای کارشناس‌های استان همان ارگان / برگشت برای اصلاح",
            "notifications": "اعلان‌های کاربران ارگان+شهرستان (مشاهده) + اعلان‌های خودش (badge)",
            "admin": "خیر",
        },
        {
            "role": "کارشناس استان",
            "code": Role.ORG_PROV_EXPERT.value,
            "forms": "همه فرم‌های ارگان خودش / فقط پرکردن",
            "reports_view": "فقط گزارش‌های ارجاع‌شده به خودش (صف خودش)",
            "reports_create": "خیر",
            "workflow": "ارسال برای مدیر استان / برگشت برای اصلاح",
            "notifications": "فقط اعلان‌های خودش",
            "admin": "خیر",
        },
        {
            "role": "مدیر استان",
            "code": Role.ORG_PROV_MANAGER.value,
            "forms": "همه فرم‌های ارگان خودش / فقط پرکردن",
            "reports_view": "همه گزارش‌های ارگان خودش",
            "reports_create": "خیر",
            "workflow": "ارسال برای دبیرخانه / برگشت برای اصلاح",
            "notifications": "اعلان‌های کاربران ارگان (مشاهده) + اعلان‌های خودش (badge)",
            "admin": "خیر",
        },
        {
            "role": "کارشناس دبیرخانه",
            "code": Role.SECRETARIAT_USER.value,
            "forms": "مشاهده همه فرم‌ها + ایجاد/ویرایش/حذف فرم",
            "reports_view": "همه گزارش‌ها",
            "reports_create": "خیر",
            "workflow": "بررسی/ارسال/درخواست اصلاح (بخش دبیرخانه)",
            "notifications": "همه اعلان‌ها (مشاهده) + اعلان‌های خودش (badge)",
            "admin": "مدیریت محدود",
        },
        {
            "role": "مدیر دبیرخانه",
            "code": Role.SECRETARIAT_ADMIN.value,
            "forms": "مشاهده همه فرم‌ها + ایجاد/ویرایش/حذف فرم",
            "reports_view": "همه گزارش‌ها",
            "reports_create": "خیر",
            "workflow": "تأیید نهایی/درخواست اصلاح",
            "notifications": "همه اعلان‌ها (مشاهده) + اعلان‌های خودش (badge)",
            "admin": "کامل",
        },
    ]

    return request.app.state.templates.TemplateResponse(
        "policy/index.html",
        {"request": request, "rows": rows, "user": user, "badge_count": get_badge_count(db, user)},
    )
