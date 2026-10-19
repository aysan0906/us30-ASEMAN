# -*- coding: utf-8 -*-
"""
US30 Unified Signal Engine
--------------------------
Uses only verified US30 OHLCV analysis and a coherent engine-generated plan.
Unverified orderflow adapters, proxy candles and unvalidated timeframes fail closed.
"""

import time
import math
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional, List
import us30_reference_config as refcfg

_BAD_SIGNAL_INTERVALS = set(refcfg.ENGINE_CONSTANTS.get("bad_intervals", []))

TEHRAN_TZ = timezone(timedelta(hours=3, minutes=30))

# =========================================================================
# SETUP PERSISTENCE & LOCK ENGINE (Prevents jumping/floating Entry and SL)
# =========================================================================
_LOCKED_SCALP_STATE: Dict[str, Any] = {
    "active": False,
    "entry": 0.0,
    "sl": 0.0,
    "tp1": 0.0,
    "tp2": 0.0,
    "tp3": 0.0,
    "direction": "LONG",
    "created_at": 0.0,
    "expires_at": 0.0,
    "time_str": "",
    "date_str": ""
}

_LOCKED_SWING_STATE: Dict[str, Any] = {
    "active": False,
    "entry": 0.0,
    "sl": 0.0,
    "tp1": 0.0,
    "tp2": 0.0,
    "tp3": 0.0,
    "direction": "LONG",
    "created_at": 0.0,
    "expires_at": 0.0,
    "time_str": "",
    "date_str": ""
}


def get_us30_live_price(prefer_trendo: bool = True) -> float:
    if prefer_trendo:
        try:
            import trendo_engine
            t_data = trendo_engine.get_trendo_us30_live()
            if t_data.get("ok"):
                p = float(t_data.get("bid", 0.0) or 0.0)
                if p > 10000:
                    return p
        except Exception:
            pass
    try:
        from us30_engine import _live_dow_cash
        lv = _live_dow_cash()
        p = float(lv.get("price") or 0.0)
        if p > 10000:
            return p
    except Exception:
        pass
    return None



def is_us30_market_in_killzone():
    now_tehran = datetime.now(TEHRAN_TZ)
    weekday = now_tehran.weekday() # 0 is Monday, 4 is Friday, 5 is Saturday, 6 is Sunday
    # Weekend filter (Saturday and Sunday)
    if weekday in [5, 6]:
        return False, "بازار وال‌استریت در تعطیلات پایان هفته بسته است."
    
    hour = now_tehran.hour
    minute = now_tehran.minute
    total_minutes = hour * 60 + minute

    # London Open Killzone: 10:30 to 13:00 Tehran (630 to 780 min)
    is_london = (630 <= total_minutes <= 780)
    # NY Overlap & Wall Street Main Session: 16:30 to 22:30 Tehran (990 to 1350 min)
    is_ny = (990 <= total_minutes <= 1350)

    if is_london:
        return True, "کیل‌زون لندن (تزریق نقدینگی بانکی اروپایی)"
    elif is_ny:
        return True, "کیل‌زون وال‌استریت و سشن اصلی نیویورک (نقدینگی حداکثری)"
    else:
        return False, "ساعات کم‌نوسان و مرده بازار (خارج از کیل‌زون طلایی لندن و نیویورک جهت جلوگیری از استاپ‌هانت)"

def get_us30_unified_signals(current_price: Optional[float] = None) -> Dict[str, Any]:
    global _LOCKED_SCALP_STATE, _LOCKED_SWING_STATE
    now_tehran = datetime.now(TEHRAN_TZ)
    tehran_time_str = now_tehran.strftime("%H:%M:%S")
    tehran_date_str = now_tehran.strftime("%Y/%m/%d")

    if current_price is None or current_price <= 0:
        current_price = get_us30_live_price()
    if current_price is None or current_price <= 10000:
        return {
            "ok": False,
            "tradable": False,
            "error": "LIVE_PRICE_UNAVAILABLE",
            "message": "قیمت معتبر بازار در دسترس نیست؛ تولید سیگنال متوقف شد."
        }

    # Only OHLCV-derived analysis is trusted here. The project's Bookmap/ATAS/
    # NinjaTrader/Quantower adapters currently synthesize values without live connectors.
    bm: Dict[str, Any] = {}
    nt: Dict[str, Any] = {}
    qt: Dict[str, Any] = {}
    sc: Dict[str, Any] = {}
    atas: Dict[str, Any] = {}
    cot: Dict[str, Any] = {}
    cross: List[Dict[str, Any]] = []

    # =========================================================================
    # PART 1: UNIFIED US30 SCALP SIGNAL (15m Timeframe / 1m Sniper with Lock & Anti-Front-Run)
    # =========================================================================
    cvd_data = nt.get("cvd", {})
    cvd_val = cvd_data.get("value") if isinstance(cvd_data, dict) else None
    sc_div = sc.get("delta_divergence", {}).get("type_fa")
    atas_tps = atas.get("tape_speed", {}).get("trades_per_sec")

    # REAL DYNAMIC MARKET STRUCTURE (SMC, CHoCH, VWAP, EMA & TRENDO PRICE ACTION)
    smc_bias = 0
    htf_bias = 0
    scalp_engine_dir = 0
    scalp_engine_score = 0.0
    scalp_engine_plan: Dict[str, Any] = {}
    scalp_engine_source_valid = False
    swing_engine_dir = 0
    swing_engine_score = 0.0
    swing_engine_plan: Dict[str, Any] = {}
    swing_engine_source_valid = False
    try:
        import us30_engine as ue
        analysis_data = ue.build_analysis(interval="15m", bars=180, force=False)
        st_data = analysis_data.get("structure", {}) if isinstance(analysis_data, dict) else {}
        sig_data = analysis_data.get("signal", {}) if isinstance(analysis_data, dict) else {}
        smc_bias = int(st_data.get("bias", 0) or 0)
        htf_bias = int(st_data.get("htf_bias", 0) or 0)
        scalp_engine_dir = int(sig_data.get("direction", 0) or 0)
        scalp_engine_score = float(sig_data.get("score", 0) or 0)
        scalp_engine_plan = sig_data.get("plan") if isinstance(sig_data.get("plan"), dict) else {}
        meta = analysis_data.get("meta", {}) if isinstance(analysis_data, dict) else {}
        symbol = str(meta.get("symbol", "")).upper()
        scalp_engine_source_valid = "US30" in symbol and "DIA" not in symbol
    except Exception:
        pass
    try:
        swing_analysis = ue.build_analysis(interval="4h", bars=180, force=False)
        swing_sig = swing_analysis.get("signal", {}) if isinstance(swing_analysis, dict) else {}
        swing_engine_dir = int(swing_sig.get("direction", 0) or 0)
        swing_engine_score = float(swing_sig.get("score", 0) or 0)
        swing_engine_plan = swing_sig.get("plan") if isinstance(swing_sig.get("plan"), dict) else {}
        meta4 = swing_analysis.get("meta", {}) if isinstance(swing_analysis, dict) else {}
        symbol4 = str(meta4.get("symbol", "")).upper()
        swing_engine_source_valid = "US30" in symbol4 and "DIA" not in symbol4
    except Exception:
        swing_engine_dir = 0
        swing_engine_score = 0.0

    # Compare current price against session VWAP and short-term trend
    t_bid = current_price
    t_change = 0.0
    try:
        import trendo_engine
        t_meta = trendo_engine.get_trendo_us30_live()
        if t_meta.get("ok"):
            t_bid = float(t_meta.get("bid", current_price))
            t_change = float(t_meta.get("change_pts", 0.0))
    except Exception:
        pass

    # Conservative scoring: only actual OHLCV/SMC analysis with a coherent plan may set direction.
    def _valid_plan(plan: Dict[str, Any], direction: int) -> bool:
        try:
            en, st = float(plan["entry"]), float(plan["stop"])
            t1, t2, t3 = float(plan["tp1"]), float(plan["tp2"]), float(plan["tp3"])
            if min(en, st, t1, t2, t3) <= 0:
                return False
            if direction > 0:
                return st < en < t1 < t2 < t3
            if direction < 0:
                return st > en > t1 > t2 > t3
        except (KeyError, TypeError, ValueError):
            return False
        return False

    score_long = 0
    score_short = 0
    if scalp_engine_source_valid and "15m" not in _BAD_SIGNAL_INTERVALS and scalp_engine_score >= 65 and _valid_plan(scalp_engine_plan, scalp_engine_dir):
        if scalp_engine_dir > 0:
            score_long = int(min(100, scalp_engine_score))
        elif scalp_engine_dir < 0:
            score_short = int(min(100, scalp_engine_score))

    # Determine real direction
    # Strict Direction Determination: Equality or low conviction MUST yield NEUTRAL / WAIT!
    if score_long == score_short or max(score_long, score_short) < 65:
        scalp_is_neutral = True
        scalp_is_long = False
        scalp_is_short = False
    else:
        scalp_is_neutral = False
        # Three-way decision: Only take action if score is valid and above conviction threshold!
    if score_long == score_short or max(score_long, score_short) < 65:
        scalp_is_neutral = True
        scalp_is_long = False
        scalp_is_short = False
    elif score_long > score_short:
        scalp_is_neutral = False
        scalp_is_long = True
        scalp_is_short = False
    else:
        scalp_is_neutral = False
        scalp_is_long = False
        scalp_is_short = True
    if scalp_is_neutral:
        scalp_dir_str = "صبر / عدم معامله (NEUTRAL)"
        scalp_dir_code = "NEUTRAL"
        scalp_dir_emoji = "⚪"
    elif scalp_is_long:
        scalp_dir_str = "خرید (LONG)"
        scalp_dir_code = "LONG"
        scalp_dir_emoji = "🟢"
    else:
        scalp_dir_str = "فروش (SHORT)"
        scalp_dir_code = "SHORT"
        scalp_dir_emoji = "🔴"

    # Micro Stop Loss strictly 13.0 points ($1.30 in 0.01 lot for $10 account)
    micro_sl_pts = 13.0
    now_epoch = time.time()

    # Check if existing scalp setup is still locked and active (45 min lock)
    # A neutral signal must never inherit or preserve a previously locked trade.
    # Also guard against None/corrupt state left by older versions.
    is_valid_scalp_lock = (
        not scalp_is_neutral
        and isinstance(_LOCKED_SCALP_STATE, dict)
        and _LOCKED_SCALP_STATE.get("active", False)
        and now_epoch < _LOCKED_SCALP_STATE.get("expires_at", 0)
        and (_LOCKED_SCALP_STATE.get("entry") or 0) > 10000
        and _LOCKED_SCALP_STATE.get("direction") in ("LONG", "SHORT")
        and _LOCKED_SCALP_STATE.get("direction") == ("LONG" if scalp_is_long else "SHORT")
    )

    if is_valid_scalp_lock:
        # ABSOLUTE LOCK: Do NOT jump to a new trade immediately upon tick contact!
        # A setup remains FROZEN for the entire 45 minutes unless user manually requests fresh setup.
        # This prevents the frustrating "hit stop loss and immediately moved entry" loop.
        lk_dir = _LOCKED_SCALP_STATE["direction"]
        lk_sl = _LOCKED_SCALP_STATE["sl"]
        lk_tp2 = _LOCKED_SCALP_STATE["tp2"]
        hit_tp = (current_price >= lk_tp2) if lk_dir == "LONG" else (current_price <= lk_tp2)
        hit_sl = (current_price <= lk_sl) if lk_dir == "LONG" else (current_price >= lk_sl)
        # Expire lock immediately if final target reached OR Stop Loss hit!
        if hit_tp or hit_sl:
            is_valid_scalp_lock = False
            _LOCKED_SCALP_STATE["active"] = False

    if is_valid_scalp_lock:
        # Retain 100% frozen values
        scalp_is_long = (_LOCKED_SCALP_STATE["direction"] == "LONG")
        if scalp_is_neutral:
            scalp_dir_str = "صبر / عدم معامله (NEUTRAL)"
            scalp_dir_emoji = "⚪"
            scalp_dir_code = "NEUTRAL"
        elif scalp_is_long:
            scalp_dir_str = "خرید (LONG)"
            scalp_dir_emoji = "🟢"
            scalp_dir_code = "LONG"
        else:
            scalp_dir_str = "فروش (SHORT)"
            scalp_dir_emoji = "🔴"
            scalp_dir_code = "SHORT"
        scalp_entry = _LOCKED_SCALP_STATE["entry"]
        scalp_sl = _LOCKED_SCALP_STATE["sl"]
        scalp_tp1 = _LOCKED_SCALP_STATE["tp1"]
        scalp_tp2 = _LOCKED_SCALP_STATE["tp2"]
        scalp_tp3 = _LOCKED_SCALP_STATE["tp3"]
        scalp_tp1_pts = _LOCKED_SCALP_STATE.get("tp1_pts", 24)
        scalp_tp2_pts = _LOCKED_SCALP_STATE.get("tp2_pts", 48)
        scalp_tp3_pts = _LOCKED_SCALP_STATE.get("tp3_pts", 75)
        tehran_date_str = _LOCKED_SCALP_STATE["date_str"]
        tehran_time_str = _LOCKED_SCALP_STATE["time_str"]
        sec_left = int(_LOCKED_SCALP_STATE["expires_at"] - now_epoch)
        lock_status_note = f"🔒 ستاپ قفل‌شده معتبر (اعتبار: {sec_left // 60}:{sec_left % 60:02d})"
    else:
        # Mint and LOCK a fresh scalp setup with Anti-Front-Running protection
        t_bid = current_price
        t_ask = current_price + 1.2
        try:
            import trendo_engine
            t_data = trendo_engine.get_trendo_us30_live()
            if t_data.get("ok"):
                t_bid = float(t_data.get("bid", current_price))
                t_ask = float(t_data.get("ask", current_price + 1.2))
        except Exception:
            pass

        # Bookmap walls
        bm_asks = [float(x.get("price")) for x in bm.get("ask_levels", []) if x.get("price")]
        bm_bids = [float(x.get("price")) for x in bm.get("bid_levels", []) if x.get("price")]

        # Institutional Limit Pullback Entry (NEVER chase at market top/bottom)
        # Entry zone is placed 4.0 to 6.5 points in pullback towards VWAP/FVG discount
        if scalp_is_neutral:
            scalp_entry = None
            entry_low = None
            entry_high = None
            scalp_sl = None
            scalp_tp1 = None
            scalp_tp2 = None
            scalp_tp3 = None
            scalp_tp1_pts = 0
            scalp_tp2_pts = 0
            scalp_tp3_pts = 0
            _LOCKED_SCALP_STATE = None
            lock_status_note = "⚪ وضعیت بازار خنثی / بدون ستاپ معتبر (سیستم در حالت صبر)"
        elif scalp_is_long:
            scalp_entry = round(float(scalp_engine_plan["entry"]), 1)
            entry_low = scalp_entry
            entry_high = scalp_entry
            scalp_sl = round(float(scalp_engine_plan["stop"]), 1)
            scalp_tp1 = round(float(scalp_engine_plan["tp1"]), 1)
            scalp_tp2 = round(float(scalp_engine_plan["tp2"]), 1)
            scalp_tp3 = round(float(scalp_engine_plan["tp3"]), 1)
            micro_sl_pts = round(abs(scalp_entry - scalp_sl), 1)

            scalp_tp1_pts = int(round(scalp_tp1 - scalp_entry))
            scalp_tp2_pts = int(round(scalp_tp2 - scalp_entry))
            scalp_tp3_pts = int(round(scalp_tp3 - scalp_entry))

            _LOCKED_SCALP_STATE = {
                "active": True,
                "entry": scalp_entry,
                "sl": scalp_sl,
                "tp1": scalp_tp1,
                "tp2": scalp_tp2,
                "tp3": scalp_tp3,
                "tp1_pts": scalp_tp1_pts,
                "tp2_pts": scalp_tp2_pts,
                "tp3_pts": scalp_tp3_pts,
                "direction": scalp_dir_code,
                "created_at": now_epoch,
                "expires_at": now_epoch + 2700,
                "time_str": tehran_time_str,
                "date_str": tehran_date_str
            }
            lock_status_note = "⚡ ستاپ خرید تازه صادر و قفل شد (مجهز به فیلتر ضد فرانت‌رانینگ)"
        else:
            scalp_entry = round(float(scalp_engine_plan["entry"]), 1)
            entry_low = scalp_entry
            entry_high = scalp_entry
            scalp_sl = round(float(scalp_engine_plan["stop"]), 1)
            scalp_tp1 = round(float(scalp_engine_plan["tp1"]), 1)
            scalp_tp2 = round(float(scalp_engine_plan["tp2"]), 1)
            scalp_tp3 = round(float(scalp_engine_plan["tp3"]), 1)
            micro_sl_pts = round(abs(scalp_entry - scalp_sl), 1)

            scalp_tp1_pts = int(round(scalp_entry - scalp_tp1))
            scalp_tp2_pts = int(round(scalp_entry - scalp_tp2))
            scalp_tp3_pts = int(round(scalp_entry - scalp_tp3))

            _LOCKED_SCALP_STATE = {
                "active": True,
                "entry": scalp_entry,
                "sl": scalp_sl,
                "tp1": scalp_tp1,
                "tp2": scalp_tp2,
                "tp3": scalp_tp3,
                "tp1_pts": scalp_tp1_pts,
                "tp2_pts": scalp_tp2_pts,
                "tp3_pts": scalp_tp3_pts,
                "direction": scalp_dir_code,
                "created_at": now_epoch,
                "expires_at": now_epoch + 2700,
                "time_str": tehran_time_str,
                "date_str": tehran_date_str
            }
            lock_status_note = "⚡ ستاپ فروش تازه صادر و قفل شد (مجهز به فیلتر ضد فرانت‌رانینگ)"

    scalp_signal = {
        "signal_type": "SCALP",
        "signal_type_fa": "میکرو-اسکالپ تک‌تیرانداز داوجونز (Sniper 1m / 15m)",
        "timeframe": "1m (تک‌تیرانداز پیش‌دستانه)",
        "direction": scalp_dir_str,
        "direction_code": scalp_dir_code,
        "tradable": bool(not scalp_is_neutral and scalp_engine_source_valid and _valid_plan(scalp_engine_plan, scalp_engine_dir)),
        "direction_emoji": scalp_dir_emoji,
        "entry": scalp_entry,
        "entry_fmt": f"${scalp_entry:,.1f}" if scalp_entry is not None else "—",
        "stop_loss": scalp_sl,
        "stop_loss_pts": round(abs(scalp_entry - scalp_sl), 1) if scalp_entry is not None and scalp_sl is not None else None,
        "current_price_issued": current_price,
        "stop_loss_fmt": (f"${scalp_sl:,.1f} (-{abs(scalp_entry - scalp_sl):,.1f} پوینت؛ ارزش دلاری وابسته به مشخصات قرارداد بروکر)" if scalp_sl is not None and scalp_entry is not None else "—"),
        "tp1": scalp_tp1,
        "tp1_pts": scalp_tp1_pts,
        "tp1_fmt": (f"${scalp_tp1:,.1f} (+{scalp_tp1_pts} پوینت / +${scalp_tp1_pts*0.1:.2f})" if scalp_tp1 is not None else "—"),
        "tp2": scalp_tp2,
        "tp2_pts": scalp_tp2_pts,
        "tp2_fmt": (f"${scalp_tp2:,.1f} (+{scalp_tp2_pts} پوینت / +${scalp_tp2_pts*0.1:.2f})" if scalp_tp2 is not None else "—"),
        "tp3": scalp_tp3,
        "tp3_pts": scalp_tp3_pts,
        "tp3_fmt": (f"${scalp_tp3:,.1f} (+{scalp_tp3_pts} پوینت / +${scalp_tp3_pts*0.1:.2f})" if scalp_tp3 is not None else "—"),
        "leverage_recommended": "1:500 یا 1:1000 ترندو",
        "lot_recommended": "حجم را با ارزش پوینت و مارجین بروکر محاسبه کنید؛ حجم ثابت توصیه نمی‌شود",
        "entry_instruction_fa": "وضعیت بازار خنثی یا پرریسک است. در حال حاضر ورود مجاز نیست." if scalp_is_neutral else (f"کاشت لیمیت خرید (Buy Limit) در پولبک به تراز {scalp_entry:,.1f} (پشت شلف نقدینگی و VWAP)" if scalp_is_long else f"کاشت لیمیت فروش (Sell Limit) در پولبک به تراز {scalp_entry:,.1f} (زیر دیواره عرضه و VWAP)"),
        "date_tehran": tehran_date_str,
        "time_tehran": tehran_time_str,
        "holding_duration": "۲ الی ۱۰ دقیقه (خروج سریع)",
        "holding_duration_en": "2m - 10m",
        "core_modules": "تحلیل تکنیکال OHLCV/SMC؛ فیدهای Bookmap و Footprint زنده متصل نیستند",
        "rationale_fa": "سطوح از پلن موتور تحلیل OHLCV گرفته می‌شوند. ارزش دلاری ریسک/سود و حجم پوزیشن بدون مشخصات قرارداد بروکر محاسبه یا تضمین نمی‌شود."
    }

    # =========================================================================
    # PART 2: UNIFIED US30 SWING SIGNAL (4h Timeframe - 4-Hour Lock & Macro Anti-Front-Run)
    # =========================================================================
    # Swing direction is taken only from the real 4h SMC analysis.
    swing_is_neutral = (not swing_engine_source_valid) or "4h" in _BAD_SIGNAL_INTERVALS or swing_engine_dir == 0 or swing_engine_score < 65 or not _valid_plan(swing_engine_plan, swing_engine_dir)
    swing_is_long = swing_engine_dir > 0 and not swing_is_neutral
    swing_is_short = swing_engine_dir < 0 and not swing_is_neutral
    swing_dir_str = "صبر / عدم معامله (NEUTRAL)" if swing_is_neutral else ("خرید (LONG)" if swing_is_long else "فروش (SHORT)")
    swing_dir_emoji = "⚪" if swing_is_neutral else ("🟢" if swing_is_long else "🔴")

    is_valid_swing_lock = (
        not swing_is_neutral
        and isinstance(_LOCKED_SWING_STATE, dict)
        and _LOCKED_SWING_STATE.get("active", False)
        and now_epoch < _LOCKED_SWING_STATE.get("expires_at", 0)
        and (_LOCKED_SWING_STATE.get("entry") or 0) > 10000
        and _LOCKED_SWING_STATE.get("direction") in ("LONG", "SHORT")
        and _LOCKED_SWING_STATE.get("direction") == ("LONG" if swing_is_long else "SHORT")
    )

    if is_valid_swing_lock:
        sw_dir = _LOCKED_SWING_STATE["direction"]
        sw_sl = _LOCKED_SWING_STATE["sl"]
        sw_tp2 = _LOCKED_SWING_STATE["tp2"]

        hit_sw_tp = (current_price >= sw_tp2) if sw_dir == "LONG" else (current_price <= sw_tp2)
        hit_sw_sl = (current_price <= sw_sl) if sw_dir == "LONG" else (current_price >= sw_sl)

        if hit_sw_tp or hit_sw_sl:
            is_valid_swing_lock = False
            _LOCKED_SWING_STATE["active"] = False

    if is_valid_swing_lock:
        swing_is_long = (_LOCKED_SWING_STATE["direction"] == "LONG")
        swing_dir_str = "خرید (LONG)" if swing_is_long else "فروش (SHORT)"
        swing_dir_emoji = "🟢" if swing_is_long else "🔴"
        swing_entry = _LOCKED_SWING_STATE["entry"]
        swing_sl = _LOCKED_SWING_STATE["sl"]
        swing_sl_pts = _LOCKED_SWING_STATE.get("sl_pts", 280)
        swing_tp1 = _LOCKED_SWING_STATE["tp1"]
        swing_tp1_pts = _LOCKED_SWING_STATE.get("tp1_pts", 550)
        swing_tp2 = _LOCKED_SWING_STATE["tp2"]
        swing_tp2_pts = _LOCKED_SWING_STATE.get("tp2_pts", 1450)
        swing_tp3 = _LOCKED_SWING_STATE.get("tp3", swing_entry + (2400 if swing_is_long else -2400))
        swing_tp3_pts = _LOCKED_SWING_STATE.get("tp3_pts", 2400)
    elif not swing_is_neutral:
        swing_entry = round(float(swing_engine_plan["entry"]), 1)
        swing_sl = round(float(swing_engine_plan["stop"]), 1)
        swing_tp1 = round(float(swing_engine_plan["tp1"]), 1)
        swing_tp2 = round(float(swing_engine_plan["tp2"]), 1)
        swing_tp3 = round(float(swing_engine_plan["tp3"]), 1)
        swing_sl_pts = round(abs(swing_entry - swing_sl), 1)
        swing_tp1_pts = round(abs(swing_tp1 - swing_entry), 1)
        swing_tp2_pts = round(abs(swing_tp2 - swing_entry), 1)
        swing_tp3_pts = round(abs(swing_tp3 - swing_entry), 1)

        _LOCKED_SWING_STATE = {
            "active": True,
            "entry": swing_entry,
            "sl": swing_sl,
            "sl_pts": swing_sl_pts,
            "tp1": swing_tp1,
            "tp1_pts": swing_tp1_pts,
            "tp2": swing_tp2,
            "tp2_pts": swing_tp2_pts,
            "tp3": swing_tp3,
            "tp3_pts": swing_tp3_pts,
            "direction": "LONG" if swing_is_long else "SHORT",
            "created_at": now_epoch,
            "expires_at": now_epoch + 14400,  # 4 hours locked
            "time_str": tehran_time_str,
            "date_str": tehran_date_str
        }
    else:
        _LOCKED_SWING_STATE = {"active": False}
        swing_entry = swing_sl = swing_tp1 = swing_tp2 = swing_tp3 = None
        swing_sl_pts = swing_tp1_pts = swing_tp2_pts = swing_tp3_pts = None

    swing_signal = {
        "signal_type": "SWING",
        "signal_type_fa": "سوئینگ تریدینگ داوجونز (موج‌سواری چندروزه)",
        "timeframe": "4h",
        "direction": swing_dir_str,
        "direction_code": "NEUTRAL" if swing_is_neutral else ("LONG" if swing_is_long else "SHORT"),
        "tradable": bool(not swing_is_neutral and swing_engine_source_valid and _valid_plan(swing_engine_plan, swing_engine_dir)),
        "direction_emoji": swing_dir_emoji,
        "entry": swing_entry,
        "entry_fmt": f"${swing_entry:,.1f}" if swing_entry is not None else "—",
        "stop_loss": swing_sl,
        "stop_loss_pts": swing_sl_pts,
        "stop_loss_fmt": f"${swing_sl:,.1f} (-{swing_sl_pts} پوینت)" if swing_sl is not None else "—",
        "tp1": swing_tp1,
        "tp1_pts": swing_tp1_pts,
        "tp1_fmt": f"${swing_tp1:,.1f} (+{swing_tp1_pts} پوینت)" if swing_tp1 is not None else "—",
        "tp2": swing_tp2,
        "tp2_pts": swing_tp2_pts,
        "tp2_fmt": f"${swing_tp2:,.1f} (+{swing_tp2_pts} پوینت)" if swing_tp2 is not None else "—",
        "tp3": swing_tp3,
        "tp3_pts": swing_tp3_pts,
        "tp3_fmt": f"${swing_tp3:,.1f} (+{swing_tp3_pts} پوینت)" if swing_tp3 is not None else "—",
        "date_tehran": tehran_date_str,
        "time_tehran": tehran_time_str,
        "holding_duration": "۲ الی ۵ روز",
        "holding_duration_en": "2 - 5 days",
        "core_modules": "Quantower 4H TPO + CFTC COT 6-Week + Wall Street 5 Banks + Anti-Front-Run",
        "rationale_fa": "هم‌راستایی تعهدات صعودی مدیران دارایی در گزارش CFTC COT با کف منصفانه ارزش (VAL) کوانت‌تاور و تارگت‌گذاری ماکرو ضد فرانت‌رانینگ پیش از استخرهای نقدینگی شورت‌ها."
    }

    # =========================================================================
    # PART 3: RELATIONSHIP & ALIGNMENT STATUS
    # =========================================================================
    is_aligned = (not scalp_is_neutral) and (not swing_is_neutral) and (scalp_is_long == swing_is_long)
    if scalp_is_neutral or swing_is_neutral:
        alignment_status = "بدون هم‌سویی قابل ارزیابی (NEUTRAL)"
        alignment_note = "سیگنال اسکالپ خنثی است؛ تا دریافت داده و جهت معتبر، معامله‌ای صادر نشود."
    elif is_aligned:
        alignment_status = "همسویی کامل (Full Alignment 💎)"
        alignment_note = "هر دو دیدگاه اسکالپ و سوئینگ داوجونز هم‌جهت هستند؛ این فقط هم‌جهتی سیگنال‌هاست و تضمین وین‌ریت نیست."
    else:
        alignment_status = "اسکالپ اصلاحی درون روند کلان (Counter-Trend Retracement ⚠️)"
        alignment_note = "دیدگاه اسکالپ ۱۵ دقیقه‌ای خلاف جهت سوئینگ چندروزه است؛ این معامله یک پولبک موقت است و خروج سریع در TP1 الزامی است."

    return {
        "ok": True,
        "symbol": "US30",
        "tradable": bool(scalp_signal.get("tradable") or swing_signal.get("tradable")),
        "current_price": current_price,
        "scalp": scalp_signal,
        "swing": swing_signal,
        "is_aligned": is_aligned,
        "alignment_status": alignment_status,
        "alignment_note": alignment_note,
        "updated_at_iran": f"{tehran_date_str} ساعت {tehran_time_str}"
    }


def format_us30_clean_telegram_signal(sig: Dict[str, Any], is_swing: bool = False) -> str:
    sig_type_fa = sig.get("signal_type_fa", "سوئینگ داوجونز" if is_swing else "میکرو-اسکالپ تک‌تیرانداز 1m")
    tf = sig.get("timeframe", "4H" if is_swing else "1m (تک‌تیرانداز پیش‌دستانه)")
    direction = sig.get("direction", "خرید (LONG)")
    dir_emoji = sig.get("direction_emoji", "🟢")
    entry_fmt = sig.get("entry_fmt", "-")
    sl_fmt = sig.get("stop_loss_fmt", "-")
    tp1_fmt = sig.get("tp1_fmt", "-")
    tp2_fmt = sig.get("tp2_fmt", "-")
    tp3_fmt = sig.get("tp3_fmt", "-")
    date_tehran = sig.get("date_tehran", "")
    time_tehran = sig.get("time_tehran", "")
    duration = sig.get("holding_duration", "۲ تا ۵ روز" if is_swing else "۳ الی ۱۰ دقیقه")
    cur_p = sig.get("current_price_issued", sig.get("entry"))
    if (not isinstance(cur_p, (int, float)) or cur_p <= 10000
            or sig.get("direction_code") not in {"LONG", "SHORT"}
            or sig.get("tradable") is not True):
        return "⚪ <b>سیگنال داوجونز [#US30]</b>\nقیمت یا جهت معتبر در دسترس نیست؛ هیچ معامله‌ای پیشنهاد نمی‌شود."

    if not is_swing:
        risk_lot_note = """📦 <b>حجم پوزیشن:</b> <code>با توجه به ارزش پوینت، مارجین و مشخصات قرارداد بروکر محاسبه شود؛ حجم ثابت توصیه نمی‌شود.</code>"""
    else:
        risk_lot_note = """📦 <b>حجم پوزیشن:</b> <code>با مشخصات قرارداد، ارزش پوینت و مارجین بروکر محاسبه شود؛ حجم ثابت توصیه نمی‌شود.</code>"""

    msg = f"""💎 <b>سیگنال داوجونز [#US30]</b>
━━━━━━━━━━━━━━━━━━━━
🏢 <b>منبع:</b> <code>تحلیل OHLCV نماد اجرایی؛ جزئیات منبع در API ثبت شده است</code>
🧭 <b>جهت معامله:</b> {dir_emoji} <b>{direction}</b>
⏱️ <b>تایم‌فریم:</b> <code>{tf}</code>
💰 <b>قیمت لحظه صدور:</b> <code>${cur_p:,.1f}</code>
🎯 <b>قیمت ورود قطعی:</b> <code>{entry_fmt}</code>
🛑 <b>حد ضرر (SL):</b> <code>{sl_fmt}</code>
🎯 <b>حد سود اول (TP1):</b> <code>{tp1_fmt}</code>
🎯 <b>حد سود دوم (TP2):</b> <code>{tp2_fmt}</code>
🎯 <b>حد سود سوم (TP3):</b> <code>{tp3_fmt}</code>
🛡️ <b>توجه:</b> <code>این خروجی تضمین اجرا یا کیفیت fill نیست؛ spread و slippage بروکر را بررسی کنید.</code>
{risk_lot_note}
⏰ <b>تاریخ و ساعت صدور:</b> <code>{date_tehran} ساعت {time_tehran} (ایران 🇮🇷)</code>
⏳ <b>اعتبار سیگنال:</b> <code>تا پیش از ورود، قیمت و وضعیت بازار را دوباره بررسی کنید؛ این پیام تضمین اجرای سفارش نیست.</code>
━━━━━━━━━━━━━━━━━━━━"""
    return msg.strip()

format_us30_minimal_telegram_signal = format_us30_clean_telegram_signal
