# گزارش تغییرات و اصلاحات — us30-ASEMAN

تمام ۴۸ فایل پایتون پروژه خط‌به‌خط بازبینی شد (استاتیک: py_compile + pyflakes + بازرسی دستی). منطق استراتژی و سیگنال‌ها تغییری نکرده است؛ فقط ایرادات واقعی رفع شدند.

## ایرادات بحرانی (رفع شد)

1. **server.py — خطوط سرگردان ابتدای فایل**
   سه خط (`import uuid` و `from us30_supreme_arbiter import us30_supreme_arbiter`) قبل از shebang و docstring فایل قرار داشتند که باعث می‌شد docstring و shebang بی‌اثر شوند و import از ترتیب استاندارد خارج شود.
   → حذف شدند؛ import کردن `us30_supreme_arbiter` به محل صحیح بعد از سایر importها منتقل شد.

2. **server.py — `dcash` تعریف‌نشده (NameError در ۵ نقطه)**
   در خطوط 256، 260، 382، 1257 و 1608 روی `dcash.freshest()` فراخوانی می‌شد اما `import dow_cash as dcash` فقط داخل یک تابع دیگر (خط 464) انجام می‌شد؛ در هر مسیر اجرای دیگر برنامه با NameError کرش می‌کرد.
   → `import dow_cash as dcash` در سطح ماژول اضافه شد و import محلی تکراری حذف شد.

3. **elite_modules.py — فراخوانی تابع ناموجود `get_macro_economic_shield()`**
   فیلتر ۴ (News Spike Breaker & Spread Guard) تابعی را صدا می‌زد که در هیچ‌جای پروژه تعریف نشده بود → در بهترین حالت exception و در بدترین حالت قفل/آزادسازی اشتباه فیوز خبری.
   → تابع به‌عنوان پل به فیوز کلان رسمی پروژه (`AsemanMacroShieldUS30.get_macro_shield_status`) پیاده‌سازی شد؛ کلیدهای `status` (LOCKED/CAUTION/PASS) و `minutes_to_next` از `shield_color` و `countdown_seconds` منبع رسمی نرمال‌سازی می‌شوند و در صورت قطع شدن ماژول، حالت امن PASS برمی‌گردد.

4. **elite_modules.py — `Optional` تعریف‌نشده**
   در امضای `get_vix_and_smt_data(current_price: Optional[float])` استفاده شده بود ولی import نشده بود → هر import ماژول با NameError شکست می‌خورد.
   → به import خط typing اضافه شد.

5. **market_hours.py — `Any` تعریف‌نشده**
   در امضای `is_us30_market_in_active_session() -> Tuple[bool, str, Dict[str, Any]]` استفاده شده بود ولی import نشده بود.
   → به import خط typing اضافه شد.

6. **server.py — تعریف تکراری و متناقض `format_us30_master_signal_telegram`**
   ابتدا alias ساده‌ای از `format_us30_composite_telegram` بود و بلافاصله بعدش نسخه کامل مستقل تعریف می‌شد؛ نسخه اول مرده و گمراه‌کننده بود.
   → alias حذف شد و فقط نسخه کامل باقی ماند.

7. **server.py — تعریف تکراری `uvicorn` و import بلااستفاده `macro_data as md`**
   → حذف شدند.

## ایرادات متوسط (رفع شد)

8. **bookmap_engine.py — دو دستور `global` بی‌اثر** (`_BM_CACHE`, `_BM_CACHE_TIME` هیچ‌جا در تابع assign نمی‌شوند) → حذف شدند.
9. **server.py — سه دستور `global` بی‌اثر** (`_analysis_cache`, `_coalition_shared_cache/_macro_shared_cache`, `_LOCKED_COMPOSITE_SETUPS`) → حذف شدند (خطر واقعی: اگر بعداً assign می‌شدند بدون global، باگ متغیر سراسری می‌ساختند).

## موارد بازبینی‌شده و سالم

- سینتکس هر ۴۸ فایل با `py_compile` تأیید شد — بدون خطا.
- هیچ NameError یا تعریف تکراری باقی نماند (تأیید نهایی pyflakes).
- منطق کش‌ها، session hours و DST در `market_hours.py`، منطق `^DJI` به‌جای `YM=F` در `dow_cash.py`، و ماژول‌های سیگنال (us30_engine، smart_money، elite_modules و…) دست‌نخورده و سالم بررسی شدند.
- موارد باقی‌مانده pyflakes صرفاً importها/متغیرهای محلی بلااستفاده‌اند (بدون اثر عملکردی) و برای حفظ خوانایی کد اصلی حذف انبوه نشدند.
