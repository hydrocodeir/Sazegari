# سامانه سازگاری با کم‌آبی (Water Compatibility)

سامانه‌ای مبتنی بر **FastAPI + HTMX + Jinja2** برای **جمع‌آوری داده‌ها**، **مدیریت فرم‌ها** و **تولید گزارش‌های شهرستانی/استانی** با **گردش‌کار چندمرحله‌ای** و **ثبت لاگ تغییرات**.  
Backend با **MySQL** (SQLAlchemy + Alembic) و کش/Badge اعلان‌ها با **Redis** پیاده‌سازی شده است.

---

## امکانات کلیدی

- مدیریت **ارگان‌ها**، **شهرستان‌ها** و **واحدهای ارگان↔شهرستان** (OrgCountyUnit)
- مدیریت کاربران و نقش‌ها (RBAC) در ۶ نقش:
  - کارشناس شهرستان / مدیر شهرستان
  - کارشناس استان / مدیر استان
  - کارشناس دبیرخانه / مدیر دبیرخانه
- فرم‌ساز و مدیریت **الگوهای فرم (FormTemplate)** با **Schema JSON**
- ثبت داده‌ها (**Submission**) به‌همراه **پیوست**
- تولید گزارش (**Report**) با امکان اتصال داده‌ها/فرم‌ها و تولید **PDF رسمی**
- گردش‌کار گزارش‌ها (State Machine) + ارجاع به گیرنده مرحله بعد
- اعلان داخلی + Badge تعداد اعلان‌های خوانده‌نشده (با Redis)
- **ثبت لاگ تغییرات گزارش** (ReportAuditLog) برای ایجاد/ویرایش/حذف و تغییرات محتوا

---

## تکنولوژی‌ها

- Python 3.11
- FastAPI + Uvicorn
- Jinja2 Templates + HTMX (UI سرور-رندر)
- SQLAlchemy 2 + Alembic (Migration)
- MySQL 8
- Redis 7
- ReportLab + arabic-reshaper + python-bidi (خروجی PDF فارسی)

---

## مفاهیم دامنه (Domain مدل)

- **Org**: ارگان
- **County**: شهرستان
- **OrgCountyUnit**: اتصال ارگان↔شهرستان (واحد اجرایی)
- **User**: کاربر (دارای role و در صورت نیاز org_id / county_id)
- **FormTemplate**: الگوی فرم (schema_json) با scope:
  - `county` فرم مخصوص یک شهرستان
  - `all` فرم عمومی ارگان برای همه شهرستان‌ها
  - `province` فرم مخصوص گزارش استانی
- **Submission**: داده ثبت‌شده بر اساس یک FormTemplate (به‌همراه فایل پیوست)
- **Report**: گزارش (نوع `county` یا `provincial`) با content_json
- **ReportSubmission**: اتصال گزارش به داده‌های ثبت‌شده
- **ReportAttachment**: پیوست‌های گزارش
- **WorkflowLog**: لاگ گردش‌کار (ارجاع‌ها/تاییدها/نیاز به اصلاح)
- **ReportAuditLog**: لاگ تغییرات محتوا/پیوست/اتصالات/… (ایجاد/ویرایش/حذف)

---

## نقش‌ها و محدوده دسترسی (RBAC)

نقش‌ها در `app/db/models/user.py` تعریف شده‌اند:

| Role | برچسب | Scope |
|---|---|---|
| `org_county_expert` | کارشناس شهرستان | org + county |
| `org_county_manager` | مدیر شهرستان | org + county |
| `org_prov_expert` | کارشناس استان | org |
| `org_prov_manager` | مدیر استان | org |
| `secretariat_user` | کارشناس دبیرخانه | global |
| `secretariat_admin` | مدیر دبیرخانه | global |

> قواعد دقیق دسترسی و اقدامات هر نقش در مسیرها/روترها و همچنین صفحه Policy Matrix قابل مشاهده است: `/policy`.

---

## گردش‌کار گزارش‌ها (Workflow)

تمام قواعد گردش‌کار به‌صورت متمرکز در `app/core/workflow.py` تعریف شده‌اند (state machine داده‌محور).

### 1) گزارش شهرستان (ReportKind = `county`)

**مسیر تایید:**

1. کارشناس شهرستان: `draft` → ارسال برای مدیر شهرستان
2. مدیر شهرستان: تایید → ارسال برای کارشناس استان
3. کارشناس استان: تایید → ارسال برای مدیر استان
4. مدیر استان: تایید نهایی → `final_approved`

**مسیر نیاز به اصلاح (بازگشت):**

- مدیر شهرستان → نیاز به اصلاح برای کارشناس شهرستان (`needs_revision`)
- کارشناس استان → نیاز به اصلاح برای مدیر شهرستان
- مدیر استان → نیاز به اصلاح برای کارشناس استان

### 2) گزارش استانی (ReportKind = `provincial`)

این گزارش پس از نهایی شدن/تایید گزارش‌های شهرستانی قابل تهیه است و توسط **کارشناس استان** ساخته می‌شود.

**مسیر تایید:**

1. کارشناس استان: `draft` → ارسال برای مدیر استان
2. مدیر استان: تایید → ارسال برای کارشناس دبیرخانه
3. کارشناس دبیرخانه: تایید → ارسال برای مدیر دبیرخانه
4. مدیر دبیرخانه: تایید نهایی → `final_approved`

**مسیر نیاز به اصلاح (بازگشت):**

- مدیر استان → نیاز به اصلاح برای کارشناس شهرستان (طبق پیکربندی workflow)
- کارشناس دبیرخانه → نیاز به اصلاح برای مدیر استان
- مدیر دبیرخانه → نیاز به اصلاح برای کارشناس دبیرخانه

> توابع مهم: `allowed_actions()`، `get_recipients()`، `can_edit()`، `can_delete()`.

---

### دیاگرام ساده گردش‌کار (Mermaid)

#### 1) گردش‌کار گزارش شهرستان
```mermaid
flowchart TD
  A[کارشناس شهرستان
ایجاد/ویرایش] -->|ارسال| B[مدیر شهرستان
بررسی]
  B -->|نیاز به اصلاح| A
  B -->|تایید و ارسال| C[کارشناس استان
بررسی]
  C -->|نیاز به اصلاح| B
  C -->|تایید و ارسال| D[مدیر استان
بررسی نهایی]
  D -->|نیاز به اصلاح| C
  D -->|تایید نهایی| E[نهایی/قفل]
```

#### 2) گردش‌کار گزارش استانی (تجمیعی)
```mermaid
flowchart TD
  P1[کارشناس استان
تهیه گزارش جامع] -->|ارسال| P2[مدیر استان ارگان
بررسی]
  P2 -->|نیاز به اصلاح| P1
  P2 -->|تایید و ارسال| P3[کارشناس دبیرخانه
بررسی]
  P3 -->|نیاز به اصلاح| P2
  P3 -->|تایید و ارسال| P4[مدیر دبیرخانه
بررسی نهایی]
  P4 -->|نیاز به اصلاح| P3
  P4 -->|تایید نهایی| P5[نهایی/قفل]
```

> اگر در UI از HTMX استفاده می‌کنید، مسیر `GET /reports/{report_id}/permissions` می‌تواند منبع truth برای نمایش/عدم نمایش دکمه‌های «ارسال/تایید/نیاز به اصلاح/حذف/ویرایش» باشد.



## ساختار پروژه (Code Structure)

```
.
├── app/
│   ├── main.py                # FastAPI app، middlewareها، routerها، صفحات HTML
│   ├── auth/                  # ورود/خروج، deps احراز هویت
│   ├── core/                  # config، security، rbac، redis، workflow
│   ├── db/
│   │   ├── models/             # ORM models
│   │   ├── session.py          # SQLAlchemy engine/session (POOL_SIZE/MAX_OVERFLOW)
│   │   └── base.py
│   ├── modules/               # روترهای دامنه (users, orgs, reports, ...)
│   ├── scripts/               # اسکریپت‌های اجرایی (migrate)
│   ├── templates/             # Jinja2 templates (HTMX-ready)
│   └── utils/                 # تولید PDF، تجمیع گزارش، اعلان‌ها، اعتبارسنجی
├── alembic/                   # migrations
├── docker-compose.yml         # web + migrate + mysql + redis
├── Dockerfile
├── requirements.txt
├── run.sh                     # اجرای محلی با uvicorn --reload
└── uploads/                   # ذخیره فایل‌های آپلود شده (volume)
```

### روترها (Modules)

- `app/auth/router.py` : login/logout و سشن
- `app/modules/orgs` : مدیریت ارگان‌ها
- `app/modules/counties` : مدیریت شهرستان‌ها
- `app/modules/org_counties` : اتصال ارگان↔شهرستان
- `app/modules/forms` : فرم‌ها و قالب‌ها
- `app/modules/submissions` : ثبت داده‌ها
- `app/modules/reports` : گزارش‌ها + workflow + PDF
- `app/modules/notifications` : اعلان‌ها
- `app/modules/users` : مدیریت کاربران
- `app/modules/policy` : Policy Matrix برای مستندسازی دسترسی‌ها

## نقشه مسیرهای کلیدی (Routes)

> نکته: علاوه بر مسیرهای زیر، **FastAPI** به‌صورت پیش‌فرض مسیرهای **/docs** و **/openapi.json** را هم ارائه می‌کند.

### عمومی
- `GET /` صفحه اصلی (UI)
- `GET /health` سلامت سرویس

### احراز هویت
- `GET /login` فرم ورود
- `POST /login` انجام ورود
- `POST /logout` خروج

### هسته دامنه (API)
- ارگان‌ها: `GET /orgs`
- شهرستان‌ها: `GET /counties`
- ارتباط ارگان↔شهرستان: `GET /org-counties`

### کاربران و دسترسی‌ها
- کاربران:  
  - `GET /users` لیست
  - `POST /users` ایجاد
  - `POST /users/{user_id}/toggle-active` فعال/غیرفعال

### فرم‌ها
- `GET /forms` لیست قالب‌ها
- `POST /forms` ایجاد/به‌روزرسانی قالب
- `POST /forms/{form_id}/delete` حذف قالب

### گزارش‌ها (مهم‌ترین مسیرها)
- `GET /reports/{report_id}` مشاهده/ویرایش (طبق مجوز نقش)
- `GET /reports/{report_id}/permissions` دریافت مجوزهای UI برای دکمه‌ها
- `POST /reports/{report_id}/action` انجام اکشن‌های گردش‌کار (ارسال، تایید، نیاز به اصلاح، نهایی‌سازی)
- بخش‌ها (Sections):
  - `POST /reports/{report_id}/sections/add`
  - `POST /reports/{report_id}/sections/update`
  - `POST /reports/{report_id}/sections/remove`
  - `POST /reports/{report_id}/sections/reorder`
- فایل و پیوست‌ها:
  - `POST /reports/{report_id}/upload` آپلود فایل داخل گزارش
  - `POST /reports/{report_id}/attach` اتصال پیوست
  - `POST /reports/{report_id}/detach` جداکردن پیوست
  - `GET /reports/{report_id}/pdf` خروجی PDF
- حذف گزارش:
  - `POST /reports/{report_id}/delete` (با ثبت لاگ)

### ارسال‌ها (Submission)
- `GET /submissions` لیست ارسال‌ها/ارجاعات
- `POST /submissions/{submission_id}/action` اکشن روی ارسال (تایید/بازگشت/…)

### اعلان‌ها
- `GET /notifications` لیست اعلان‌ها
- `POST /notifications/mark-read` خوانده‌شدن اعلان‌ها


---

## راه‌اندازی با Docker Compose (پیشنهادی)

پیش‌نیاز: Docker / Docker Desktop

```bash
docker compose up --build
```

سپس:
- برنامه: `http://localhost:8000`
- دیتابیس: `localhost:3306` (MySQL)
- Redis: `localhost:6379`

**ورود اولیه (قابل تنظیم با ENV):** `admin / 123`

پاک‌کردن کامل داده‌ها:

```bash
docker compose down -v
```

### نکته مهم درباره migrate
در `docker-compose.yml` سرویس `migrate` قبل از `web` اجرا می‌شود و کارهای زیر را انجام می‌دهد:
- صبر تا آماده شدن MySQL
- اجرای `alembic upgrade head` (یا stamp برای دیتابیس legacy)
- ساخت ادمین پیش‌فرض در صورت فعال بودن `AUTO_CREATE_ADMIN`
- ساخت داده‌های نمونه برای تست سریع در صورت فعال بودن `AUTO_SEED_SAMPLE`

---

## اجرای محلی (Linux/Mac)

1) ساخت محیط و نصب وابستگی‌ها:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

2) تنظیم ENV:

```bash
cp .env.example .env
# سپس MYSQL_DSN و REDIS_URL را مطابق سیستم خود تنظیم کنید
```

3) اجرا:

```bash
chmod +x run.sh
./run.sh
```

> برای اجرای Migration در حالت محلی:

```bash
alembic upgrade head
```

---

## تنظیمات محیطی (ENV)

فایل‌ها:
- `.env.example` برای اجرای محلی
- `.env.docker` برای Docker Compose

متغیرهای اصلی (بر اساس `app/core/config.py` و بخش‌هایی از `app/db/session.py` و Dockerfile):

### اپلیکیشن
- `APP_NAME` نام برنامه
- `ENV` مقدار پیشنهادی: `dev` / `prod`

### امنیت و سشن
- `SECRET_KEY` (اجباری برای production)
- `COOKIE_SECURE` اگر پشت HTTPS هستید `true`
- `COOKIE_SAMESITE` مقدارهای رایج: `lax` / `strict`
- `SESSION_MAX_AGE_SECONDS` مدت اعتبار سشن

### CORS
- `CORS_ALLOW_ORIGINS` لیست جداشده با کاما یا `*`
- `CORS_ALLOW_CREDENTIALS` اگر کوکی و credential می‌خواهید `true`

### دیتابیس و کش
- `MYSQL_DSN` نمونه:
  - محلی: `mysql+pymysql://user:pass@127.0.0.1:3306/water_compat?charset=utf8mb4`
  - داکر: `mysql+pymysql://water:waterpass@db:3306/water_compat?charset=utf8mb4`
- `REDIS_URL` نمونه: `redis://redis:6379/0`

### عملکرد (Pool/Workers)
- `UVICORN_WORKERS` تعداد workerها (Dockerfile از این مقدار استفاده می‌کند)
- `DB_POOL_SIZE` اندازه pool اتصال SQLAlchemy
- `DB_MAX_OVERFLOW` حداکثر overflow

### فایل‌ها
- `UPLOAD_DIR` مسیر ذخیره فایل‌ها (در داکر: `/app/uploads`)
- `MAX_UPLOAD_MB` حداکثر حجم آپلود

### Bootstrap (ادمین اولیه)
- `AUTO_CREATE_ADMIN` اگر `true` و کاربر وجود نداشته باشد ساخته می‌شود
- ساخت داده‌های نمونه برای تست سریع در صورت فعال بودن `AUTO_SEED_SAMPLE`
- `DEFAULT_ADMIN_USERNAME`
- `DEFAULT_ADMIN_PASSWORD`
- `DEFAULT_ADMIN_FULL_NAME`

---

## تولید PDF و دانلود فایل‌ها

- فایل‌های آپلودی در مسیر `UPLOAD_DIR` ذخیره می‌شوند و از مسیر `/uploads` به‌صورت static سرو می‌شوند.
- تولید PDF در `app/utils/pdf_report.py` انجام می‌شود (ReportLab + تنظیمات فارسی).

**نکته داکر:**
در compose یک volume به `./uploads:/app/uploads` وصل شده است. اگر دانلود/نمایش فایل مشکل داشت:
- مطمئن شوید پوشه `uploads/` وجود دارد و قابل نوشتن است.
- اگر reverse proxy دارید، مسیر `/uploads` را مسدود نکرده باشد.

---

## مهاجرت دیتابیس (Alembic)

- فایل‌ها در `alembic/versions/` قرار دارند.
- کانتینر `migrate` به‌صورت خودکار `upgrade head` را انجام می‌دهد.

اجرای دستی:

```bash
alembic upgrade head
```

ساخت migration جدید (نمونه):

```bash
alembic revision -m "add something" --autogenerate
```

---

## نکات توسعه و نگهداری

- قواعد گردش‌کار را فقط در `app/core/workflow.py` تغییر دهید تا در همه جا یکسان بماند.
- برای تغییر سیاست‌های دسترسی (RBAC)، علاوه بر روترها، صفحه `/policy` را هم به‌روز نگه دارید.
- برای گزارش خطاهای HTML/HTMX، handlerهای `HTTPException` و `Exception` در `app/main.py` مسیر بازگشت مناسب می‌دهند (به‌خصوص 401).

---

## عیب‌یابی سریع

### 1) بالا نیامدن web به خاطر دیتابیس
- در Docker Compose مطمئن شوید سرویس `db` healthy شده است.
- مقدار `MYSQL_DSN` را بررسی کنید.

### 2) دانلود/نمایش فایل‌های آپلودی کار نمی‌کند
- `UPLOAD_DIR` و mount مربوط به `uploads` را بررسی کنید.
- اگر روی ویندوز/WSL هستید، permission پوشه را چک کنید.

### 3) خطای 401 و برگشت به login
- این رفتار عمدی است: برای درخواست‌های HTMX هدر `HX-Redirect` تنظیم می‌شود.

---

## مجوز (License)

در صورت نیاز، فایل LICENSE اضافه کنید و نوع مجوز را مشخص نمایید.
