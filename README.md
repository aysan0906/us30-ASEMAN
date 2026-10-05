# داشبورد اختصاصی US30 / Dow Jones — ASEMAN Render Ready

این پروژه نسخه اختصاصی **US30 / Dow Jones** است که با معماری پروژه کریپتوی ASEMAN ساخته شده و موتور اطلاعات/تحلیل داو از پروژه قبلی `dow-analyzer1` گرفته شده است.

## معماری

- `FastAPI` تک‌سرویس مانند پروژه ASEMAN
- `index.html` داشبورد RTL فارسی، بدون نیاز به build فرانت‌اند
- `market_data.py` لایه Provider داده با env vars برای Render
- `smart_money.py` موتور Smart Money / ICT پروژه قبلی داو
- `us30_engine.py` تبدیل خروجی موتور به JSON مناسب داشبورد
- `render.yaml` و `Dockerfile` آماده Deploy

## اجرا روی Render

| فیلد | مقدار |
|---|---|
| Runtime | Python 3 |
| Build Command | `pip install -r requirements.txt` |
| Start Command | `uvicorn server:app --host 0.0.0.0 --port $PORT --proxy-headers` |
| Health Check | `/healthz` |

یا از فایل `render.yaml` استفاده کنید.

## متغیرهای محیطی

```env
DATA_PROVIDER=yahoo
DATA_API_KEY=
DATA_SYMBOL=DIA
DISPLAY_SCALE=100
DATA_FALLBACK=true
DEFAULT_INTERVAL=1h
WITH_COALITION=false
```

### نکته مهم درباره قیمت US30

به‌صورت پیش‌فرض از `DIA` استفاده شده چون داده تاریخی رایگان و پایدار دارد. قیمت DIA تقریباً یک‌صدم داوجونز است، پس:

```env
DATA_SYMBOL=DIA
DISPLAY_SCALE=100
```

اگر provider پولی شما قیمت واقعی US30/DJ30 را مستقیم برمی‌گرداند:

```env
DATA_SYMBOL=US30
DISPLAY_SCALE=1
```

## Providerهای پشتیبانی‌شده

```env
DATA_PROVIDER=yahoo       # بدون کلید، پیش‌فرض
DATA_PROVIDER=twelvedata  # نیازمند DATA_API_KEY
DATA_PROVIDER=polygon     # نیازمند DATA_API_KEY
DATA_PROVIDER=finnhub     # نیازمند DATA_API_KEY
DATA_PROVIDER=alphavantage# نیازمند DATA_API_KEY
```

اگر API انتخاب‌شده خطا بدهد و `DATA_FALLBACK=true` باشد، سیستم به Yahoo/DIA برمی‌گردد.

## Endpointها

| مسیر | کاربرد |
|---|---|
| `/` | داشبورد اصلی |
| `/healthz` | سلامت سرویس |
| `/api/status` | وضعیت کلی سرویس، provider و بازار |
| `/api/providers` | وضعیت provider و env |
| `/api/ticker?interval=1h` | قیمت آخر US30 |
| `/api/candles?interval=1h&bars=180` | کندل‌ها |
| `/api/analyze?interval=1h&bars=180` | تحلیل کامل Smart Money |
| `/api/plan?interval=1h` | پلن معامله و سایزینگ آموزشی |

## لایه‌های تحلیلی

- ساختار بازار: BOS / CHoCH
- FVG و Order Block
- نقدینگی BSL / SSL و Sweep
- Volume Profile: POC / VAH / VAL
- جریان نهادی: Delta / OBV / CMF / MFI / VWAP
- HFT Footprint
- Fake Trend Detector
- پلن معامله: Entry / SL / TP1 / TP2 / TP3
- سایزینگ آموزشی بر اساس Equity و Risk %

## هشدار

این پروژه ابزار تحلیلی و آموزشی است و توصیه مالی یا دستور معامله نیست. قبل از معامله واقعی، خبرهای اقتصادی آمریکا، اسپرد/کمیسیون، مشخصات قرارداد بروکر و ریسک حساب را بررسی کنید.
