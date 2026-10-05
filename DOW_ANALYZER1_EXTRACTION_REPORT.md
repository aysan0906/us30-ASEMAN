# گزارش استخراج کامل منابع مفید `dow-analyzer1` برای داوجونز / US30

منبع: `https://github.com/Tanha2419/dow-analyzer1.git`

این گزارش مشخص می‌کند چه چیزهایی از پروژه قبلی داوجونز/طلا برای نسخه جدید `US30_ASEMAN_RENDER` استخراج شد و هرکدام کجا استفاده می‌شود.

## خلاصه عملیاتی

پروژه قبلی `dow-analyzer1` چند بخش بسیار مهم مخصوص داوجونز داشت که فراتر از موتور SMC بودند. در این نسخه، علاوه بر `smart_money.py` که قبلاً وارد شده بود، لایه‌های زیر هم اضافه شدند:

- پروفایل رسمی US30 و قوانین تبدیل DIA×100
- قیمت نقدی داوجونز با منبع ^DJI، YM=F و DIA
- ساعت بازار NYSE، تعطیلات، نیم‌روزها و Killzone تهران
- Context بین‌بازاری DXY/US10Y/SPX/NDX/VIX
- فیلترهای نهادی و veto rules
- orderflow، delta/CVD، block trades، seasonality و الگوها
- regime/AI: Hurst، Kalman، ADX، WaveTrend، واگرایی، SuperTrend، Chandelier
- options/volatility: DIA options، PCR، Max Pain، IV، skew، VIX term structure
- داده‌های واقعی کلان: FOMC، FRED، Treasury، VIX percentile، earnings/news
- تقویم اقتصادی actual/forecast/previous و surprise score
- quality filter و آستانه‌های بک‌تست‌شده برای US30
- trade plan کامل با دلیل entry/SL/TP/invalidation
- agent قبلی به‌صورت endpoint سنگین و کش‌شده

## فایل‌های منتقل‌شده به ریشه پروژه جدید

| فایل | کاربرد برای US30 | وضعیت |
|---|---|---|
| `assets.py` | پروفایل US30: `DIA`, `DIA options`, `display_scale=100`, قوانین DXY/VIX/Yields | منتقل و endpoint شد |
| `dow_cash.py` | انتخاب بهترین قیمت داو: ^DJI در بازار باز، YM=F منهای basis در بازار بسته، DIA×factor | منتقل و endpoint شد |
| `market_hours.py` | NYSE session، pre/post market، تعطیلات، half-day، Killzone تهران | منتقل و endpoint شد |
| `market_context.py` | MTF، intermarket، news/calendar، trade gate | منتقل و endpoint شد |
| `institutional.py` | intermarket veto، liquidation map، reference levels، feature vector نهادی | منتقل شد؛ توسط agent/layers استفاده می‌شود |
| `orderflow.py` | delta/CVD، block trades، seasonality، candle/chart patterns | منتقل و endpoint شد |
| `regime_ai.py` | رژیم بازار، Hurst، Kalman، WaveTrend، واگرایی، SuperTrend، anomaly/ML | منتقل و endpoint شد |
| `volatility.py` | options analytics، IV، skew، Max Pain، VIX complex | منتقل و endpoint شد |
| `real_data.py` | FOMC/FRED/Treasury/VIX percentile/Finnhub/AlphaVantage | منتقل و endpoint شد |
| `econ_actual.py` | actual/forecast/previous، surprise score، ForexFactory critical events | منتقل و endpoint شد |
| `macro_data.py` | FRED macro block، macro score، yield curve، earnings | منتقل و endpoint شد |
| `macro_extras.py` | killzone timer، DXY correlation، FOMC countdown | منتقل و endpoint شد |
| `sentiment_ext.py` | CNN Fear & Greed، StockTwits، COT reference | منتقل و endpoint شد |
| `signal_filter.py` | quality gate بر اساس بک‌تست؛ آستانه US30 minimum=32 و strong=40 | منتقل و endpoint شد |
| `validated.py` | موتور سیگنال اعتبارسنجی‌شده تاریخی | منتقل و endpoint شد |
| `tradeplan.py` | پلن معامله کامل، دلایل، invalidation، خروجی متنی/HTML | منتقل و endpoint شد |
| `agent.py` | ایجنت قبلی ترکیبی داو: SMC + MTF + macro + orderflow + regime + options | منتقل و endpoint سنگین شد |
| `window.py` | کیفیت ساعت معامله بر اساس هزینه/نوسان | منتقل و endpoint شد |
| `cross_asset.py` | همبستگی طلا↔داو و position sizing کراس‌دارایی | منتقل و endpoint شد |
| `live_feed.py` | طراحی فید زنده/SSE و polling Yahoo | منتقل شد ولی auto-start نشده تا FastAPI سبک بماند |
| `board.py`, `events.py`, `journal.py`, `snapshot.py`, `autolog.py`, `qa_bot.py` | نقشه سطوح، رویدادها، ژورنال، snapshot، Q&A | منتقل شدند برای استفاده آتی و سازگاری agent |
| `web_api.py` | سازنده payload قدیمی Flask | منتقل شد به‌عنوان منبع سازگاری/مرجع |
| `backtest_results.json`, `journal.jsonl`, `snapshot_cache.json` | داده‌های بک‌تست، ژورنال و snapshot قبلی | منتقل شدند |

## فایل‌های قدیمی که فقط به‌عنوان مرجع نگهداری شدند

در مسیر `dow_analyzer1_original/` نگهداری شده‌اند:

- `server.py` قدیمی Flask
- `index.html` قدیمی
- `embedded_ui.py`
- `engine_backtest.py`
- `smc_backtest.py`
- workflowهای GitHub Actions
- README و requirements اصلی

علت: معماری نسخه جدید باید تک‌سرویس FastAPI/Render بماند، پس Flask server قدیمی اجرا نمی‌شود ولی برای رجوع و توسعه بعدی حفظ شده است.

## Endpointهای جدید اضافه‌شده

| Endpoint | توضیح |
|---|---|
| `/api/dow/manifest` | فهرست تمام ماژول‌های استخراج‌شده و کاربردشان |
| `/api/dow/profile` | پروفایل US30/DIA، قوانین intermarket و display_scale |
| `/api/dow/cash` | قیمت نقدی داو با ^DJI/YM=F/DIA و basis زنده |
| `/api/dow/hours` | وضعیت بازار، Killzone تهران، تعطیلات آینده |
| `/api/dow/window` | کیفیت پنجره زمانی معامله |
| `/api/dow/quality?score=40&interval=1d` | ارزیابی کیفیت سیگنال با آستانه بک‌تست‌شده |
| `/api/dow/backtest` | خلاصه نتایج بک‌تست US30 |
| `/api/dow/macro` | macro block قدیمی بر پایه FRED/earnings |
| `/api/dow/extras` | killzone timer، DXY correlation، FOMC countdown |
| `/api/dow/econ` | تقویم اقتصادی actual/forecast/previous و surprise |
| `/api/dow/context` | context بین‌بازاری، news/calendar و trade gate |
| `/api/dow/orderflow?interval=1h` | orderflow، CVD، block trades، seasonality و patterns |
| `/api/dow/volatility` | options/IV/skew/VIX complex |
| `/api/dow/real?what=treasury` | منابع واقعی Treasury/FRED/Finnhub/AlphaVantage/VIX |
| `/api/dow/sentiment` | Fear & Greed، StockTwits و sentiment خارجی |
| `/api/dow/intelligence?interval=1h` | regime/AI بدون اجرای agent کامل |
| `/api/dow/validated?interval=1d` | سیگنال اعتبارسنجی‌شده |
| `/api/dow/tradeplan?interval=1h` | پلن معامله کامل پروژه قبلی |
| `/api/dow/cross` | همبستگی طلا↔داو و sizing کراس‌دارایی |
| `/api/dow/agent` | ایجنت کامل قبلی؛ سنگین و کش‌شده |
| `/api/dow/suite?light=true` | بسته تجمیعی سبک از منابع مهم |

## نتایج بک‌تست مهم استخراج‌شده

از `backtest_results.json` و `signal_filter.py`:

### US30-1D

- تعداد سیگنال‌ها: `468`
- Win rate کل: `45.1%`
- Avg R کل: `+0.012R`
- دسته Strong: `204` نمونه، Win rate `52.5%`، Avg R `+0.21R`
- Grade B: `80` نمونه، Win rate `62.5%`، Avg R `+0.47R`
- Grade A+: `6` نمونه، Win rate `83.3%`، Avg R `+1.019R`

### US30-1H

- تعداد سیگنال‌ها: `165`
- Win rate کل: `41.2%`
- Avg R کل: `-0.041R`
- نتیجه مهم: تایم‌فریم‌های intraday در `signal_filter.py` به‌عنوان نامناسب/پرریسک علامت خورده‌اند و تایم‌فریم روزانه معتبرتر است.

### آستانه‌های معتبر US30

از `signal_filter.py`:

```text
minimum = 32
strong  = 40
best_r  = 2.5
```

توضیح: سیگنال‌های زیر ۳۲ در بک‌تست نویز محسوب شدند. سیگنال‌های بالای ۴۰ دسته قوی‌اند.

## نکات مهم استخراج‌شده برای منطق داوجونز

1. **DIA فقط proxy است، نه خود شاخص.**  
   بنابراین `display_scale=100` یا فاکتور پویا باید رعایت شود.

2. **قیمت مرجع پلتفرم‌ها معمولاً ^DJI است.**  
   وقتی بازار بسته است، `dow_cash.py` از YM=F منهای basis استفاده می‌کند.

3. **VIX برای داوجونز همیشه وتوی خرید نیست.**  
   در `assets.py` توضیح داده شده که ممیزی ۲۰۲۶-۰۹-۱۹ نشان داده VIX بالا در بعضی دوره‌ها نقطه خرید تاریخی بوده؛ پس فقط هشدار نوسان است، نه وتوی قطعی.

4. **دلار و بازده اوراق برای داوجونز مهم‌اند.**  
   DXY قوی و US10Y صعودی معمولاً فشار منفی روی US30 دارند.

5. **تایم‌فریم روزانه معتبرترین لایه بک‌تست‌شده است.**  
   intraday برای نمایش و timing مفید است، اما quality gate اصلی باید روزانه را وزن بیشتری بدهد.

6. **معکوس‌کردن جهت سیگنال داو رد شده است.**  
   در `signal_filter.py` توضیح داده شده که آزمون t نشان داد آن ایده تصادفی بوده؛ مشکل اصلی کیفیت سیگنال است، نه جهت.

## env vars مفید جدید

برای فعال‌کردن کامل منابع واقعی قدیمی می‌توان این کلیدها را در Render گذاشت:

```env
FRED_KEY=
FINNHUB_KEY=
ALPHAVANTAGE_KEY=
SNAPSHOT_KEY=
```

کلید واقعی نباید داخل کد یا چت قرار بگیرد.

## تست انجام‌شده

- همه فایل‌های Python پروژه جدید syntax-check شدند.
- endpointهای سبک جدید تست شدند.
- `/api/dow/suite?light=true` تست شد.
- `/api/dow/profile`, `/api/dow/hours`, `/api/dow/quality`, `/api/dow/backtest`, `/api/dow/intelligence` تست شدند.

## جمع‌بندی

پس از دریافت مرجع کامل ۱ اکتبر ۲۰۲۶، دو فایل دیگر نیز اضافه شد:

- `US30_DATA_SOURCES_FULL_REFERENCE.md` — ثبت کامل منابع Yahoo، نمادهای ^DJI/DIA/YM=F، تنظیمات ترِندو، Killzoneها، ثابت‌های موتور و اعداد اندازه‌گیری‌شده.
- `us30_reference_config.py` — همان مرجع به شکل config اجرایی برای endpointهای `/api/dow/reference` و `/api/dow/broker`.

همچنین اصلاح مهم انجام شد: DXY برای داوجونز دیگر وتوی جهت‌دار نیست، چون اندازه‌گیری مرجع `r=-0.012` و `t=-0.27` دارد؛ در `assets.py` وزن DXY برای US30 صفر شد و `market_context.py` وزن intermarket را از پروفایل می‌خواند.

اکنون پروژه جدید سه منبع را با هم دارد:

1. معماری و UI از ASEMAN
2. موتور SMC از `dow-analyzer1`
3. همه لایه‌های مفید داوجونز از `dow-analyzer1`: قیمت نقدی، context، macro، orderflow، regime، volatility، quality/backtest، tradeplan و agent قدیمی
