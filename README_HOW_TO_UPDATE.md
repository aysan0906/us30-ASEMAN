# راهنمای انتشار نسخهٔ اصلاح‌شده

1. ابتدا ZIP کامل را باز کنید و یک backup از مخزن فعلی نگه دارید.
2. قبل از استفاده، در Render مقدار `DATA_PROVIDER` و `DATA_SYMBOL` را برای provider واقعی نماد اجرایی US30 تنظیم کنید. تنظیم پیش‌فرض DIA فقط proxy نمایشی است و سیگنال اجرایی از آن صادر نمی‌شود.
3. در Render یک `ADMIN_SECRET_KEY` تصادفی و طولانی تعریف کنید. کلید را در URL یا GitHub commit نکنید.
4. تا پایان بررسی feed و بک‌تست، `ENABLE_TELEGRAM_AUTOPILOT=0` و `ENABLE_TELEGRAM_INTERACTIVE_BOT=0` بمانند.
5. پس از deploy، `/healthz` و سپس `/api/dow/guard?interval=1d&fresh=true` را بررسی کنید. گارد باید فقط با دادهٔ واقعی US30 بررسی شود.
6. برای تست regression محلی:

```bash
DISABLE_BACKGROUND_WORKERS=1 python -m unittest discover -s tests -v
python -m compileall -q .
```

7. کلید مدیریت را در کادر مدیریت داشبورد وارد و Enter بزنید تا وضعیت تلگرام/ژورنال بارگذاری شود.

این نسخه فقط از نظر تست‌های ذکرشده بررسی شده است؛ آن را قبل از تأیید feed واقعی، گارد و تست عملیاتی به ارسال خودکار معاملات متصل نکنید.
