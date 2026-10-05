# ممیزی دوباره مرجع داوجونز — آیا همه چیز گرفته شد؟

این فایل پس از پیام کامل کاربر ایجاد شد تا پوشش مرجع در پروژه کنترل شود.

## وضعیت پوشش

| بخش مرجع | وضعیت | محل پیاده‌سازی / نگهداری |
|---|---|---|
| Yahoo chart endpoint + User-Agent + فیلتر None | کامل | `market_data.py` |
| سقف تاریخچه تایم‌فریم‌های Yahoo | کامل | `us30_reference_config.py`, `US30_DATA_SOURCES_FULL_REFERENCE.md` |
| تقسیم کار `^DJI` / `DIA` / `YM=F` | کامل | `dow_cash.py`, `us30_engine.py`, `/api/dow/cash`, `/api/ticker` |
| basis زنده فیوچرز | کامل | `dow_cash.py` |
| نمادهای بین‌بازاری و SMT peers | کامل | `assets.py`, `market_context.py`, `us30_reference_config.py` |
| DXY weight=0 برای داو | کامل و اصلاح‌شده | `assets.py`, `institutional.py`, `market_context.py`, `aseman_resources.py` |
| منابع کلان رایگان | کامل به‌عنوان مرجع و بخشی پیاده‌سازی‌شده | `real_data.py`, `econ_actual.py`, `sentiment_ext.py`, `macro_data.py`, `us30_reference_config.py` |
| منابع کلیددار FRED/Finnhub/AlphaVantage | کامل به‌عنوان optional env؛ برای AlphaVantage هر دو `ALPHA_KEY` و `ALPHAVANTAGE_KEY` پشتیبانی می‌شود | `.env.example`, `real_data.py`, README |
| رد Finnhub/TwelveData رایگان برای هسته اصلی | ثبت شد | `US30_DATA_SOURCES_FULL_REFERENCE.md` |
| تنظیمات ترِندو، اسپرد، حساب ۱۰ دلاری | کامل | `us30_reference_config.py`, `execution_guard.py`, `/api/dow/broker` |
| ساعات بازار و Killzoneها | کامل | `market_hours.py`, `us30_reference_config.py`, `/api/dow/hours` |
| ثابت‌های موتور: THRESHOLD/BEST_R/BAD_INTERVALS/COST/HORIZON | کامل | `signal_filter.py`, `us30_reference_config.py`, `execution_guard.py` |
| پروفایل کامل US30 | کامل و اصلاح‌شده | `assets.py` |
| ATR و ریسک تایم‌فریم‌ها | ثبت شد | `us30_reference_config.py`, `/api/dow/reference` |
| پروفایل ساعتی اسپرد/دامنه | ثبت شد | `us30_reference_config.py`, `/api/dow/reference` |
| توزیع ۱۵ دقیقه اول NY | ثبت شد | `us30_reference_config.py`, `execution_guard.py` reference |
| لبه تایم‌فریم‌ها | ثبت شد | `us30_reference_config.py`, `signal_filter.py` |
| بک‌تست اسکالپ ۶۱ میلیون تیک | ثبت شد؛ داده خام در workspace نیست | `us30_reference_config.py` |
| جست‌وجوی ۷۶ ترکیبی ORB | ثبت شد؛ ماژول/داده خام در workspace نیست | `us30_reference_config.py` |
| اثر محدودکردن حد ضرر | ثبت شد | `us30_reference_config.py` |
| فیلترهای جهت ORB | ثبت خلاصه‌ای در مرجع؛ کد عملیاتی اضافه نشده چون داده خام/nyopen.py در workspace نیست | `US30_DATA_SOURCES_FULL_REFERENCE.md` |
| ساعت طلایی tick-data | ثبت شد | `us30_reference_config.py` |
| ناپایداری سالانه ORB | ثبت شد | `us30_reference_config.py` |
| تله‌های ۱ تا ۱۶ | بخش‌های عملی مهم اعمال شد؛ فهرست ثبت شد | `us30_reference_config.py`, `US30_DATA_SOURCES_FULL_REFERENCE.md` |
| Render/GitHub Actions/cron/snapshot infra | ثبت شد؛ معماری فعلی FastAPI با uvicorn حفظ شد | `us30_reference_config.py`, `render.yaml` |
| اگر از صفر می‌ساختم | ثبت شد و بخش‌های مهم اعمال شد | `us30_reference_config.py` |

## مواردی که نمی‌توانستم از workspace استخراج کنم

در پیام کاربر به این مسیرها اشاره شده بود، اما در workspace فعلی وجود ندارند:

```text
/home/user/منابع-و-تنظیمات-داوجونز.md
/home/user/گزارش-تایم‌فریم-داوجونز.md
/home/user/گزارش-اسکالپ-نیویورک.md
/home/user/راهنمای-قانون-اسکالپ.md
/home/user/dow-dashboard/nyopen.py
/home/user/dow-data/
```

بنابراین:

- اعداد و نتایج موجود در متن کاربر ثبت شدند.
- اما ماژول عملیاتی ORB/nyopen و داده خام ۶۱ میلیون تیک وارد پروژه نشد، چون فایل/داده در workspace نبود.

## اصلاح مهم پس از ممیزی

### trap شماره ۶: آستانه ۳۲ فقط برای score هم‌مقیاس validated.py است

پیش از این، `execution_guard.py` آستانه ۳۲ را روی score تحلیل جاری هم اعمال می‌کرد. این می‌توانست همان تله‌ای باشد که در مرجع آمده بود. اصلاح شد:

- برای تایم‌فریم‌های intraday، گارد مستقیم block می‌کند و آن‌ها را فقط timing می‌داند.
- برای daily، گارد تلاش می‌کند score را از `validated.py` بگیرد.
- اگر `validated.py` در دسترس نباشد، ورود واقعی را تأیید نمی‌کند و پیام scale mismatch می‌دهد.

## نتیجه نهایی ممیزی

مرجع متنی کامل ثبت شد و بخش‌های عملی قابل اجرا وارد کد شد. تنها چیزهایی که وارد نشده‌اند، فایل‌ها/داده‌هایی هستند که در workspace فعلی وجود ندارند: `dow-dashboard/nyopen.py` و `dow-data` tick/minute data.
