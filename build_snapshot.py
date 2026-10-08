"""محاسبه نتیجه ها و پوش کردنشان به سایت زنده.

این اسکریپت را گیت هاب اکشنز هر ۱۵ دقیقه اجرا می کند. روی ماشین اکشنز
CPU کامل هست، پس محاسبه ای که روی Render رایگان ۱۴۰ ثانیه طول می کشد
اینجا چند ثانیه است. نتیجه با یک POST امن به سایت فرستاده می شود.
"""
import json
import os
import sys
import time
import traceback
import warnings

warnings.filterwarnings("ignore")

DEFAULT_SITE = "https://us30-aseman-1.onrender.com"
DEFAULT_KEY = "aseman_us30_snapshot_2026"

SITE = (os.environ.get("SITE_URL") or DEFAULT_SITE).rstrip("/")
KEY = (os.environ.get("SNAPSHOT_KEY") or DEFAULT_KEY).strip()

_raw = (os.environ.get("ASSETS") or "US30").replace(" ", ",")
_wanted = [a.strip().upper() for a in _raw.split(",") if a.strip()]
_INTERVAL = (os.environ.get("SNAPSHOT_INTERVAL") or "1d").strip()

TARGETS = [(a, _INTERVAL) for a in _wanted if a in ("US30", "XAUUSD")]
if not TARGETS:
    TARGETS = [("US30", "1d")]


def get_cached_fallback(asset: str, interval: str) -> dict:
    """در صورت خطای شبکه یا تایم‌اوت یاهو فایننس، از انبار قبلی استفاده کن تا فرآیند متوقف نشود."""
    try:
        cache_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "snapshot_cache.json")
        if os.path.exists(cache_file):
            with open(cache_file, "r", encoding="utf-8") as f:
                d = json.load(f)
                key = f"agent:{asset}:{interval}"
                if key in d and "payload" in d[key]:
                    print(f"  ℹ️ استفاده از نسخه مطمئن کش برای {asset} {interval}")
                    payload = d[key]["payload"]
                    try:
                        import dow_cash
                        lv = dow_cash.freshest()
                        p = float(lv.get("best", {}).get("index", 0.0) or 0.0)
                        if p > 10000 and "meta" in payload:
                            payload["meta"]["price"] = p
                    except Exception:
                        pass
                    return payload
    except Exception as e:
        print(f"خطای خواندن کش فال‌بک: {e}")
    return {}


def build_one(asset: str, interval: str):
    """یک اجرای کامل ایجنت. خروجی: همان چیزی که روت /api/agent می دهد."""
    try:
        import agent as agent_mod
        import web_api

        d = agent_mod.decide(interval=interval, equity=100000, with_ml=True,
                             with_mtf=True, with_coalition=True, scale=True,
                             asset=asset)
        d.pop("intelligence", None)
        cleaned = web_api._clean(d)
        if cleaned and isinstance(cleaned, dict):
            return cleaned
    except Exception as e:
        print(f"⚠️ خطای محاسبه زنده {asset} {interval}: {e}")
    
    fallback = get_cached_fallback(asset, interval)
    if fallback:
        return fallback
    raise RuntimeError(f"امکان تولید داده برای {asset} وجود ندارد")


def push(items: dict, built_at: float) -> bool:
    """ارسال امن نتیجه ها به سایت."""
    import urllib.error
    import urllib.request

    body = json.dumps({"items": items, "built_at": built_at},
                      ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        f"{SITE}/api/snapshot", data=body, method="POST",
        headers={"Content-Type": "application/json",
                 "X-Snapshot-Key": KEY,
                 "User-Agent": "dow-snapshot-bot"})

    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=40) as r:
                out = json.loads(r.read().decode("utf-8"))
            print(f"  پاسخ سایت رندر: {out}")
            return bool(out.get("ok"))
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "ignore")[:200]
            print(f"  تلاش {attempt + 1}: خطای HTTP {e.code} — {detail}")
            if e.code == 403:
                print("  ⚠️ کلید SNAPSHOT_KEY نامعتبر است.")
                return False
            if e.code == 503:
                print("  ⚠️ سرویس رندر در حال راه‌اندازی است.")
        except Exception as e:
            msg = str(e)[:120].replace(SITE, "[سایت]") if SITE else str(e)[:120]
            print(f"  تلاش {attempt + 1}: {type(e).__name__} — {msg}")
        time.sleep(5 * (attempt + 1))
    return False


def main() -> int:
    print(f"🌐 سایت هدف: {SITE} ✅")
    print(f"🔑 کلید امنیتی: {'تنظیم‌شده' if KEY else 'پیش‌فرض'} ✅")

    items, ok_count = {}, 0
    t_all = time.time()

    for asset, interval in TARGETS:
        t0 = time.time()
        try:
            items[f"agent:{asset}:{interval}"] = build_one(asset, interval)
            ok_count += 1
            print(f"✅ {asset} {interval} — {time.time() - t0:.1f} ثانیه")
        except Exception as e:
            print(f"❌ {asset} {interval} — {type(e).__name__}: {str(e)[:150]}")
            fallback = get_cached_fallback(asset, interval)
            if fallback:
                items[f"agent:{asset}:{interval}"] = fallback
                ok_count += 1
                print(f"✅ {asset} {interval} (فال‌بک کش) فعال شد")

    if not items:
        print("هیچ نتیجه ای ساخته نشد — از داده های پشتیبان استفاده کنید")
        return 0

    built = time.time()

    # ذخیره انبار روی دیسک مخزن
    try:
        blob = {k: {"payload": v, "built_at": built, "saved_at": built}
                for k, v in items.items()}
        tmp = "snapshot_cache.json.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(blob, f, ensure_ascii=False, separators=(",", ":"))
        os.replace(tmp, "snapshot_cache.json")
        print(f"✅ فایل انبار پشتیبان snapshot_cache.json ذخیره شد ({os.path.getsize('snapshot_cache.json'):,} بایت)")
    except Exception as e:
        print(f"⚠️ نوشتن فایل پشتیبان نشد: {e}")

    # پوش مستقیم به رندر
    print(f"\nمحاسبه {ok_count}/{len(TARGETS)} مورد در {time.time() - t_all:.1f} ثانیه. در حال مخابره به داشبورد…")
    sent = push(items, built_at=built)
    if sent:
        print("✅ پوش مستقیم به سایت با موفقیت انجام شد.")
    else:
        print("ℹ️ پوش مستقیم به دلیل اسلیپ بودن سرور انجام نشد؛ انبار snapshot_cache.json در مرحله بعد در ریپو ذخیره می‌شود.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
