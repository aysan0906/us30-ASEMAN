# گزارش استخراج منابع مفید ASEMAN برای داوجونز / US30

این فایل نتیجه‌ی استخراج و تبدیل بخش‌های کاربردی ریپوی `ASEMAN` برای داشبورد اختصاصی `US30_ASEMAN_RENDER` است.

## ماژول‌های استخراج/استفاده‌شده

| منبع در ASEMAN | وضعیت در پروژه US30 | کاربرد برای داوجونز |
|---|---|---|
| `fastfetch.py` | کپی شد به `US30_ASEMAN_RENDER/fastfetch.py` | fetch موازی، timeout کنترل‌شده و cache کوتاه برای منابع Yahoo/macro/news |
| `institutional_addons.py::EconomicCalendarEngine` | بازنویسی شد در `aseman_resources.py::AsemanMacroShieldUS30` | تقویم CPI/NFP/GDP/PCE/FOMC، پنجره فیوز خبری، سناریوی اثر روی US30 |
| `EconomicCalendarEngine.fetch_live_leading_indicators` | بازنویسی شد | DXY، US10Y، VIX، Gold، Oil، SPX/NDX و US30/DIA به‌عنوان شاخص‌های پیشرو |
| `institutional_addons.py::NewsCircuitBreaker` | بازنویسی شد | فیوز خبری بازار سهام با Yahoo Finance RSS و کلیدواژه‌های ریسک/رالی |
| `institutional_addons.py::OptionsEngine` | بازطراحی شد | تحلیل آپشن DIA/SPY: Put/Call Ratio، Max Pain و دیوارهای Call/Put |
| `institutional_addons.py::KellyRiskEngine` | بازنویسی شد | محاسبه سایز پوزیشن US30، Half-Kelly، EV، لوریج امن و Notional |
| ایده‌ی `GoldenSixCoreEngine` | بازطراحی شد | شش فیلتر نهادی مخصوص US30: Macro Shield، DXY/US10Y، VIX، breadth، order flow، news/options |
| ایده‌ی Alpha/Correlation در ASEMAN | بازطراحی شد | Alpha Matrix برای DIA در برابر SPY/QQQ/IWM و سکتورها |
| `macro_journal.json` | الگو استخراج شد | ژورنال رویدادهای کلان US30 با وضعیت Pending/Verified |
| `agent_advisor_engine.py` | منطق توضیح فارسی اقتباس شد | متن‌های فارسی قابل‌فهم برای پنل‌های Macro/Kelly/News |

## مواردی که عمداً مستقیم منتقل نشدند

این بخش‌ها در ASEMAN کریپتو-محور هستند و برای داوجونز فقط در صورت درخواست به‌صورت Cross-Market اختیاری معنی دارند:

- on-chain metrics
- DEX / liquidity pool data
- funding rate و open interest کریپتو
- BTC dominance
- token unlocks
- stablecoin supply ratio
- whale wallet tracking

## فایل‌های جدید/تغییرکرده

- `aseman_resources.py` — هسته‌ی جدید منابع استخراج‌شده از ASEMAN برای US30.
- `fastfetch.py` — fetcher موازی ASEMAN.
- `server.py` — endpointهای جدید `/api/aseman/*` و اتصال `aseman_suite` به `/api/analyze`.
- `index.html` — کارت‌های جدید داشبورد برای Macro Shield، Golden Filters، News، Options، Kelly و Alpha Matrix.
- `README.md` — باید endpointهای جدید و توضیح استخراج را پوشش دهد.

## Endpointهای جدید

| Endpoint | توضیح |
|---|---|
| `/api/aseman/macro` | Macro Shield، تقویم کلان، DXY/US10Y/VIX/Gold/Oil |
| `/api/aseman/news` | News Circuit Breaker مخصوص US30 |
| `/api/aseman/options?symbol=DIA` | Put/Call Ratio، Max Pain، دیوارهای آپشن |
| `/api/aseman/kelly` | محاسبه Kelly/EV/Position Size |
| `/api/aseman/golden` | شش فیلتر طلایی نهادی US30 |
| `/api/aseman/alpha` | Alpha Matrix بازار آمریکا |
| `/api/aseman/journal` | ژورنال کلان US30 |
| `/api/aseman/suite` | همه منابع استخراج‌شده در یک خروجی |
| `/api/analyze?...&include_aseman=true` | تحلیل اصلی US30 به‌همراه `aseman_suite` |

## نکات Deploy روی Render

- همچنان تک‌سرویس FastAPI است.
- نیازی به کلید جدید اجباری ندارد؛ منابع live فعلی با Yahoo/RSS کار می‌کنند.
- برای provider قیمت اصلی، همان envهای قبلی (`DATA_PROVIDER`, `DATA_API_KEY`, ...) پابرجاست.
- کلید واقعی API نباید داخل کد یا چت قرار بگیرد؛ فقط در Render Environment Variables تنظیم شود.

## هشدار

همه خروجی‌ها ابزار تحلیلی/آموزشی‌اند و توصیه مالی محسوب نمی‌شوند. مخصوصاً در پنجره CPI/NFP/FOMC، ریسک شکار نقدینگی و شکست جعلی روی US30 زیاد است.
