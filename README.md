# Water Compatibility System (FastAPI + HTMX + MySQL + Redis)

سامانه جمع‌آوری داده‌ها و تولید گزارش‌های سازگاری با کم‌آبی با گردش‌کار سازمانی.

## ویژگی‌ها (خلاصه)
- مدیریت ارگان/شهرستان/واحدهای ارگان-شهرستان
- مدیریت کاربران و نقش‌ها (کارشناس/مدیر شهرستان و استان + دبیرخانه)
- فرم‌ساز گرافیکی (بدون نوشتن JSON) + اعتبارسنجی داده‌ها
- ثبت داده‌ها (Submission) با فایل پیوست
- گزارش‌ساز (Intro + چند فرم + نتیجه‌گیری) + گردش‌کار ارجاعی
- اعلان داخلی + Badge فقط برای اعلان‌های خوانده‌نشده
- PDF رسمی با هدر ثابت/شماره صفحه/امضا و قالب اداری

---

## اجرای سریع با Docker Compose (پیشنهادی)
پیش‌نیاز: Docker Desktop

```bash
docker compose up --build
```

سپس:
- برنامه: http://localhost:8000
- ورود اولیه (قابل تنظیم): `admin / admin123`

برای پاک‌کردن کامل داده‌ها:
```bash
docker compose down -v
```

### تنظیمات مهم (Docker)
فایل `.env.docker` را بررسی کنید:
- `MYSQL_DSN` / `REDIS_URL`
- `UVICORN_WORKERS` (مثلاً 4)
- `DB_POOL_SIZE` / `DB_MAX_OVERFLOW`
- `AUTO_CREATE_ADMIN` و اطلاعات ادمین پیش‌فرض
- `COOKIE_SECURE` (اگر پشت HTTPS هستید True کنید)

---

## اجرای محلی (Linux/Mac)
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# .env را مطابق MySQL/Redis خودتان تنظیم کنید
chmod +x run.sh
./run.sh
```

---

## ورود اولیه
اگر `AUTO_CREATE_ADMIN=true` باشد و کاربر `DEFAULT_ADMIN_USERNAME` وجود نداشته باشد،
در زمان Startup یک کاربر ادمین ساخته می‌شود. برای محیط واقعی توصیه می‌شود:
- رمز را تغییر دهید
- یا `AUTO_CREATE_ADMIN=false` کنید و کاربر را دستی بسازید

---

## مسیرهای اصلی
- /login
- /orgs (مدیریت ارگان‌ها)
- /counties (مدیریت شهرستان‌ها)
- /org-counties (اتصال ارگان↔شهرستان)
- /forms (فرم‌ها؛ ایجاد/ویرایش فقط دبیرخانه)
- /users (مدیریت کاربران)
- /submissions (ثبت داده‌ها بر اساس فرم)
- /reports (ایجاد گزارش، اتصال فرم‌ها، گردش‌کار، PDF)
- /notifications (اعلان‌ها)
- /policy (Policy Matrix برای مستندسازی دسترسی‌ها)

---

## نکته فنی
- Redis برای cache کوتاه‌مدت Badge اعلان‌های خوانده‌نشده استفاده می‌شود.
- برای محیط production بهتر است مهاجرت دیتابیس با Alembic اضافه شود (در این نسخه `create_all` استفاده شده است).
