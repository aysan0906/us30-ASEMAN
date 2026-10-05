# منابع داده و تنظیمات کامل داوجونز — مرجع اجرایی سایت جدید

این فایل مرجع کاربر را به شکل قابل نگهداری داخل پروژه ثبت می‌کند. تاریخ مرجع: ۱ اکتبر ۲۰۲۶.

## 1) هسته داده: Yahoo Finance Chart API

```text
GET https://query1.finance.yahoo.com/v8/finance/chart/{SYMBOL}
```

پارامترها:

```text
interval = 1m | 2m | 5m | 15m | 30m | 1h | 1d | 1wk | 1mo
range = 1d | 5d | 1mo | 3mo | 6mo | 1y | 2y | 5y | max
includePrePost = true | false
Header: User-Agent: Mozilla/5.0
```

Path پاسخ:

```text
chart.result[0].timestamp
chart.result[0].indicators.quote[0].open/high/low/close/volume
chart.result[0].meta.regularMarketPrice
```

نکته: مقدارهای `None` داخل آرایه‌ها طبیعی است و باید فیلتر شود. پیاده‌سازی فعلی در `market_data.py` از endpoint مستقیم Yahoo با header اجباری استفاده می‌کند.

سقف تاریخچه:

| TF | سقف عملی Yahoo |
|---|---|
| 1m | 7 روز |
| 5m | 60 روز |
| 15m | 60 روز |
| 30m | 60 روز |
| 1h | 730 روز |
| 1d | بلندمدت / max |

## 2) سه نماد داوجونز و تقسیم کار

| نماد | چیست | کاربرد |
|---|---|---|
| `^DJI` | شاخص نقدی Dow | قیمت لحظه‌ای و نمایشی وقتی بازار باز است |
| `DIA` | ETF داوجونز | کندل تاریخی و تحلیل؛ `DIA × 100 ≈ US30` |
| `YM=F` | فیوچرز E-mini Dow | ساعات بسته بودن بورس: `YM=F - live basis` |

اندازه‌گیری ۲۰۲۶-۰۹-۲۳ در برابر ترِندو ۵۱٬۹۱۶:

```text
^DJI      51,864    اختلاف -52
DIA×100   51,800    اختلاف -116
YM=F      52,325    اختلاف +409
```

فرمول basis:

```text
cash_estimate = YM=F_now - basis
basis = YM=F_at_last_overlap - ^DJI_at_last_overlap
```

هشدار: basis ثابت نیست و باید زنده محاسبه شود. ماژول `dow_cash.py` همین کار را انجام می‌دهد و `us30_engine.py` قیمت نمایشی را از آن می‌گیرد.

## 3) نمادهای بین‌بازاری

| نماد | معنی | انتظار اولیه | وزن نهایی برای US30 |
|---|---|---:|---:|
| `DX-Y.NYB` | DXY | -1 | 0.00 |
| `^TNX` | US10Y | -1 | 0.18 |
| `^GSPC` | SPX | +1 | 1.00 |
| `^NDX` | NDX | +1 | 1.00 |
| `^VIX` | VIX | -1 | 0.35 هشدار نوسان |

نتیجه اندازه‌گیری مهم:

```text
DXY ↔ Dow: r=-0.012, t=-0.27 => بی‌معنا، وزن ۰
US10Y ↔ Dow: t=-1.50 => ضعیف، وزن ۰.۱۸
```

پس تله رایج «دلار قوی = داوجونز ضعیف» در این سایت اعمال نمی‌شود. DXY فقط زمینه‌ای است نه veto.

SMT peers برای داوجونز:

```json
["^GSPC", "^NDX"]
```

## 4) منابع اقتصاد کلان بدون کلید

| منبع | URL |
|---|---|
| VIX History CSV | `https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv` |
| ForexFactory this week | `https://nfs.faireconomy.media/ff_calendar_thisweek.json` |
| ForexFactory next week | `https://nfs.faireconomy.media/ff_calendar_nextweek.json` |
| Biquote calendar | `https://biquote.io/api/calendar` |
| FOMC calendar | `https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm` |
| Treasury yield curve | `https://home.treasury.gov/resource-center/data-chart-center/` |
| COT | `https://www.cftc.gov/dea/newcot/f_disagg.txt` |
| CNN Fear & Greed | `https://production.dataviz.cnn.io/index/fearandgreed/graphdata` |
| StockTwits | `https://api.stocktwits.com/api/2/streams/symbol/{SYMBOL}.json` |

## 5) منابع اختیاری کلیددار

```env
FRED_KEY=
FINNHUB_KEY=
ALPHA_KEY=
ALPHAVANTAGE_KEY=  # alias پشتیبانی‌شده
```

اگر کلید نباشد، آن بخش باید بی‌صدا رد شود و سایت کار کند.

منابع ردشده برای هسته اصلی رایگان:

- Finnhub رایگان: تأخیر/محدودیت/غیرتجاری؛ برای کندل US30 مناسب نیست.
- TwelveData رایگان: شاخص‌ها در پلن پولی، سقف ۸ درخواست در دقیقه و محدودیت روزانه.

## 6) تنظیمات بروکر ترِندو و حساب نمونه

```text
بروکر: Trendo ≈ FOREXCOM:US30
US30 spread NY session: 0.70 points
US30 spread other hours: 2.10 points
Balance: 10 USD
Leverage: 50
Min volume: 0.01 lot
1 lot US30 = 1 USD per point
0.01 lot = 0.01 USD per point
```

محاسبه نمونه:

```text
Notional = price × 1.0 × 0.01 ≈ 508.44 USD
Margin = 508.44 / 50 = 10.17 USD
```

نتیجه: با ۱۰ دلار، ۰.۰۱ لات US30 حدود ۰.۱۷ دلار کسری مارجین دارد.

## 7) ساعات و Killzoneها

داوجونز به وقت تهران:

```text
تابستان: 17:00 → 23:30
بعد از 1 نوامبر 2026: 18:00 → 00:30
```

Killzoneهای تابستان تهران:

| key | نام | بازه | وزن |
|---|---|---|---:|
| asia | دامنه آسیا | 04:00-09:30 | 0.35 |
| london | باز شدن لندن | 11:30-14:30 | 0.85 |
| ny_pre | پیش‌گشایش نیویورک | 16:30-17:00 | 0.30 |
| ny_am | باز شدن نیویورک | 17:00-20:00 | 1.00 |
| ny_pm | بعدازظهر نیویورک | 20:00-22:30 | 0.55 |
| ny_close | بسته شدن | 22:30-23:30 | 0.20 |

## 8) ثابت‌های موتور

```python
THRESHOLD_US30 = dict(minimum=32.0, strong=40.0, evidence_n=144, win_rate=56.9, avg_r=0.399, t=3.98)
BEST_R_US30 = 2.5
BAD_INTERVALS = {"1h", "5m", "15m", "30m"}
COST_PCT_US30 = 0.012
VALIDATED_STOP_ATR = 1.0
```

نتیجه: تنها لبه تاییدشده اصلی روی تایم‌فریم روزانه است. Intraday برای timing و نمایش مفید است، اما quality gate اصلی باید وزن روزانه را جدی‌تر بگیرد.

## 9) اعداد اندازه‌گیری‌شده مهم

ATR / ریسک ۰.۰۱ لات:

| TF | ATR اخیر | ATR بلندمدت | ریسک ۰.۰۱ لات | حساب لازم برای ریسک ۲٪ |
|---|---:|---:|---:|---:|
| 1D | 510 | 570 | $5.10 | $255 |
| 4H | 382 | 410 | $3.82 | $191 |
| 1H | 168 | 164 | $1.68 | $84 |
| 15M | 48 | 79 | $0.48 | $24 |
| 5M | 25 | 43 | $0.25 | $13 |

توزیع دامنه ۱۵ دقیقه اول نیویورک:

```text
P10=81, P25=105, P50=143, P75=192, P90=245 points
```

لبه تایم‌فریم:

| TF | میانگین R | موتور | t | وضعیت |
|---|---:|---:|---:|---|
| 1D | +0.201 | +0.399 | 3.98 | معتبر |
| 4H | +0.016 | — | 1.46 | نامعتبر |
| 1H | -0.017 | -0.077 | 0.98 | نامعتبر |
| 5M | +0.025 | — | 0.62 | نامعتبر |
| 1M | -0.083 | — | -7.25 | قطعاً بد |
