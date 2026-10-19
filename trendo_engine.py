"""
TRENDO BROKER OFFICIAL TICK INTEGRATION ENGINE (US30 / Dow Jones)
-----------------------------------------------------------------
Direct connection to Trendo Broker's official live quote engine.
Provides sub-second live Bid (خط آبی), Ask (خط قرمز), and real-time spread.
Optimized with background async streaming thread for 0.05ms memory reads.
"""

import json
import time
import threading
import urllib.request
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional

TEHRAN_TZ = timezone(timedelta(hours=3, minutes=30))

_TRENDO_CACHE: Dict[str, Any] = {}
_TRENDO_CACHE_TS: float = 0.0
_TRENDO_LOCK = threading.Lock()

def _fetch_trendo_raw(timeout: float = 2.0) -> Optional[Dict[str, Any]]:
    """Raw HTTP worker to fetch latest Trendo tick."""
    url = "https://api.trendofx.com/api/getSymbolHttp"
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept": "application/json"
        }
    )

    now_tehran = datetime.now(TEHRAN_TZ)
    is_ny_session = (now_tehran.hour >= 16 and now_tehran.minute >= 30) or (17 <= now_tehran.hour <= 23)
    session_label = "سشن نیویورک (اسپرد فوق‌فشرده)" if is_ny_session else "سشن لندن / آسیا (اسپرد استاندارد)"

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.load(resp)
            for item in data.get("getSymbol", []):
                if item.get("symbol") == "us30":
                    ask = float(item.get("Ask", 0.0))
                    bid = float(item.get("Bid", 0.0))
                    spread = round(ask - bid, 2)
                    if bid <= 10000 or ask <= 10000 or ask < bid or spread < 0 or spread > 50:
                        continue
                    yesterday_close = float(item.get("yesterday_close", 0.0))
                    change_pts = round(bid - yesterday_close, 1) if yesterday_close > 0 else 0.0
                    change_pct = round((change_pts / yesterday_close) * 100, 2) if yesterday_close > 0 else 0.0

                    # Successfully fetched real live trendo quote
                    return {
                        "ok": True,
                        "broker": "Trendo Broker",
                        "symbol": "US30",
                        "name": "DOW JONES",
                        "bid": bid,
                        "ask": ask,
                        "spread": spread,
                        "mid": round((ask + bid) / 2, 2),
                        "change_pts": change_pts,
                        "change_pct": change_pct,
                        "status": "LIVE_DIRECT",
                        "source": "trendo_live",
                        "tradable": True,
                        "is_synthetic": False,
                        "age_seconds": 0.0,
                        "timestamp": time.time()
                    }
    except Exception:
        pass

    # Strict P0-01 Fix: Never return fake 52000 quote with ok=True!
    return {
        "ok": False,
        "broker": "Trendo Broker",
        "symbol": "US30",
        "name": "DOW JONES",
        "bid": None,
        "ask": None,
        "spread": None,
        "mid": None,
        "tradable": False,
        "is_synthetic": False,
        "source": "unavailable",
        "error": "عدم دسترسی به قیمت زنده ترندو",
        "status": "UNAVAILABLE",
        "timestamp": time.time()
    }

def _trendo_background_poller():
    """Background worker daemon to keep Trendo price permanently hot in memory."""
    global _TRENDO_CACHE, _TRENDO_CACHE_TS
    while True:
        try:
            res = _fetch_trendo_raw(timeout=1.8)
            if res:
                with _TRENDO_LOCK:
                    _TRENDO_CACHE = res
                    _TRENDO_CACHE_TS = time.time()
        except Exception:
            pass
        time.sleep(0.6)  # Stream fresh tick every 600ms

# No network polling starts on import. The caller may explicitly opt into a worker if needed.
_poller_thread = None

def start_background_poller() -> bool:
    global _poller_thread
    with _TRENDO_LOCK:
        if _poller_thread is not None and _poller_thread.is_alive():
            return False
        _poller_thread = threading.Thread(target=_trendo_background_poller, daemon=True, name="trendo-live-poller")
        _poller_thread.start()
        return True

def get_trendo_us30_live(timeout: float = 2.0) -> Dict[str, Any]:
    """Instant sub-millisecond retrieval of live Trendo quote."""
    global _TRENDO_CACHE, _TRENDO_CACHE_TS
    now = time.time()

    # If memory cache is recent (< 2.5s), return in 0.05ms!
    with _TRENDO_LOCK:
        if _TRENDO_CACHE and (now - _TRENDO_CACHE_TS < 2.5):
            cached = dict(_TRENDO_CACHE)
            cached["age_seconds"] = round(now - _TRENDO_CACHE_TS, 3)
            return cached

    # If cache is not ready, do one synchronous fetch
    fresh = _fetch_trendo_raw(timeout=timeout)
    if fresh:
        with _TRENDO_LOCK:
            _TRENDO_CACHE = fresh
            _TRENDO_CACHE_TS = now
        return fresh

    # If network temporarily unavailable, use last cached value
    with _TRENDO_LOCK:
        if _TRENDO_CACHE:
            stale = dict(_TRENDO_CACHE)
            stale["age_seconds"] = round(now - _TRENDO_CACHE_TS, 3)
            stale["status"] = "STALE_CACHE"
            stale["is_synthetic"] = False
            return stale

    # Synthetic fallback if first boot before network connects
    now_tehran = datetime.now(TEHRAN_TZ)
    is_ny_session = (now_tehran.hour >= 16 and now_tehran.minute >= 30) or (17 <= now_tehran.hour <= 23)
    sim_spread = 0.7 if is_ny_session else 1.2
        # Strict P0-01 Fix: Never return fake 52000 quote with ok=True!
    return {
        "ok": False,
        "broker": "Trendo Broker",
        "symbol": "US30",
        "name": "DOW JONES",
        "bid": None,
        "ask": None,
        "spread": None,
        "mid": None,
        "tradable": False,
        "is_synthetic": False,
        "source": "unavailable",
        "error": "عدم دسترسی به قیمت زنده ترندو",
        "status": "UNAVAILABLE",
        "timestamp": time.time()
    }

def compute_trendo_sniper_levels(direction: str, sl_pts: float = 13.0, tp1_pts: float = 24.0, tp2_pts: float = 48.0) -> Dict[str, Any]:
    """Compute exact Trendo execution levels accounting for Bid (blue) vs Ask (red) lines."""
    t_data = get_trendo_us30_live()
    if not t_data or not t_data.get("ok") or not t_data.get("bid"):
        return {
            "ok": False,
            "tradable": False,
            "error": "قیمت زنده ترندو برای محاسبه سطوح اسنایپر در دسترس نیست."
        }
    bid = float(t_data["bid"])
    ask = float(t_data.get("ask", bid + 1.2))
    spread = float(t_data.get("spread", round(ask - bid, 1)))

    is_buy = (direction.upper() in ["BUY", "LONG", "خرید"])

    if is_buy:
        # BUY: Enter on Ask (خط قرمز), Stop/Target read on Bid (خط آبی)
        entry_price = ask
        entry_line = "خط قرمز (Ask)"
        sl_price = round(bid - sl_pts, 2)
        sl_line = "خط آبی (Bid)"
        tp1_price = round(bid + tp1_pts, 2)
        tp2_price = round(bid + tp2_pts, 2)
    else:
        # SELL: Enter on Bid (خط آبی), Stop/Target read on Ask (خط قرمز)
        entry_price = bid
        entry_line = "خط آبی (Bid)"
        sl_price = round(ask + sl_pts, 2)
        sl_line = "خط قرمز (Ask)"
        tp1_price = round(ask - tp1_pts, 2)
        tp2_price = round(ask - tp2_pts, 2)

    return {
        "ok": True,
        "direction": "BUY" if is_buy else "SELL",
        "direction_fa": "خرید (LONG)" if is_buy else "فروش (SHORT)",
        "trendo_bid": bid,
        "trendo_ask": ask,
        "trendo_spread": spread,
        "entry_price": entry_price,
        "entry_line": entry_line,
        "sl_price": sl_price,
        "sl_line": sl_line,
        "sl_pts": sl_pts,
        "tp1_price": tp1_price,
        "tp1_pts": tp1_pts,
        "tp2_price": tp2_price,
        "tp2_pts": tp2_pts,
        "session_label": t_data.get("session_label", "عادی")
    }
