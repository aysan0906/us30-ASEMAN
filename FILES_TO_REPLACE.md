# فایل‌های لازم برای جایگزینی در ریپوی us30-ASEMAN

این پکیج کل پروژه نیست؛ فقط فایل‌هایی است که باید در ریشه ریپو جایگزین/اضافه شوند.

## فایل‌های ضروری برای سایت

- `server.py` — endpointهای جدید `/api/dow/chat`, `/api/dow/institutional-layers`, `/api/snapshot`.
- `index.html` — UI جدید شبیه ASEMAN با کارت‌های نهادی، چت ایجنت، هیت‌مپ، تقویم و ماژول‌های دکمه‌ای.
- `engine_backtest.py` — لازم برای فعال شدن واقعی `validated.py` و `/api/dow/validated`.

## فایل‌های زیرساخت اختیاری ولی پیشنهادی

- `build_snapshot.py` — محاسبه snapshot روی GitHub Actions و ارسال به Render.
- `.github/workflows/snapshot.yml` — اجرای زمان‌بندی‌شده snapshot.
- `.github/workflows/keepalive.yml` — بیدار نگه داشتن سرویس/health check.

## فایل‌های مستندات/تنظیمات

- `.env.example` — placeholderهای env مثل `SNAPSHOT_KEY`, `ALPHA_KEY`, `FRED_KEY`.
- `README.md` — توضیح endpointهای جدید.
- `US30_REFERENCE_AUDIT.md` — ممیزی پوشش مرجع داوجونز.

## بعد از آپلود در GitHub

1. فایل‌ها را دقیقاً در همین مسیرها جایگزین کنید.
2. در Render یک Manual Deploy بزنید، یا با push به GitHub بگذارید Render خودش deploy کند.
3. برای snapshot، در Render و GitHub Actions یک مقدار یکسان برای `SNAPSHOT_KEY` بگذارید.
4. در GitHub Secrets مقدارهای زیر را بگذارید اگر می‌خواهید Actions فعال شود:
   - `SITE_URL` = آدرس public سایت Render، نه dashboard internal link
   - `SNAPSHOT_KEY` = همان کلیدی که در Render Environment گذاشته‌اید

## حداقل جایگزینی اگر عجله دارید

اگر فقط می‌خواهید UI و endpointها کار کنند:

- `server.py`
- `index.html`
- `engine_backtest.py`

را جایگزین کنید و Deploy بزنید.
