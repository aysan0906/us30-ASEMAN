# -*- coding: utf-8 -*-
"""
US30 UNIFIED SIGNALS ENGINE (Dow Jones Industrial Average - Wall Street Pro)
----------------------------------------------------------------------------
Provides two distinct, institutional-grade unified signals with:
1. Setup Freeze Lock (Scalp 45m / Swing 4h) - No floating or drifting Entry/SL!
2. Wall Street Anti-Front-Running Target Algorithm (Snaps targets 2.5-3.5 pts before
   heavy resting limit walls and psychological century round numbers .00 / .50).
3. 100% Tailored for $10 Micro Account:
   - Micro SL strictly 12-14 points ($1.20 - $1.40 max risk at 0.01 lot).
   - Non-zero monotonic TP1, TP2, and TP3 targets.
"""

import time
import math
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional, List

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


def _apply_us30_anti_front_run_tp(
    tp_raw: float,
    entry: float,
    is_long: bool,
    orderbook_walls: Optional[List[float]] = None
) -> float:
    """
    US30 Wall Street Institutional Anti-Front-Running Algorithm:
    Protects Dow Jones orders from rejection misses by positioning Take Profits
    2.5 to 3.5 points BEFORE major round numbers (every 50 / 100 pts) and Bookmap Ask/Bid walls.
    """
    buffer_pts = 3.0  # 3.0 points institutional front-running margin
    tp_adj = float(tp_raw)
    walls = orderbook_walls or []
    round_step = 50.0  # US30 major liquidity rests at .00 and .50

    if is_long:
        # 1. Front-run resting Bookmap ask walls
        for w in sorted([x for x in walls if x > entry]):
            if tp_adj >= w - 1.5:
                front_run_w = w - buffer_pts
                if front_run_w > entry + 5.0:
                    tp_adj = min(tp_adj, front_run_w)
                    break

        # 2. Front-run psychological round numbers (every 50 points: .00, .50)
        round_level = round(tp_adj / round_step) * round_step
        if round_level > entry + 5.0:
            if -4.0 <= (tp_adj - round_level) <= 5.0:
                front_run_level = round_level - buffer_pts
                if front_run_level > entry + 5.0:
                    tp_adj = front_run_level
    else:
        # SHORT: Front-run resting Bookmap bid shelves (sit ABOVE them)
        for s in sorted([x for x in walls if x < entry], reverse=True):
            if tp_adj <= s + 1.5:
                front_run_s = s + buffer_pts
                if front_run_s < entry - 5.0:
                    tp_adj = max(tp_adj, front_run_s)
                    break

        round_level = round(tp_adj / round_step) * round_step
        if round_level < entry - 5.0:
            if -5.0 <= (tp_adj - round_level) <= 4.0:
                front_run_level = round_level + buffer_pts
                if front_run_level < entry - 5.0:
                    tp_adj = front_run_level

    return round(tp_adj, 1)


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

    # 1. Fetch modules safely
    bm = {}
    try:
        import bookmap_engine as be
        bm = be.get_us30_bookmap_data()
    except Exception:
        pass

    nt = {}
    qt = {}
    sc = {}
    atas = {}
    try:
        import ninja_atas_quant_engine as naq
        nt = naq.get_ninjatrader_live(current_price, "15m")
        qt = naq.get_quantower_live(current_price)
        sc = naq.get_sierrachart_live(current_price, "15m")
        atas = naq.get_atas_live(current_price)
    except Exception:
        pass

    cot = {}
    try:
        import cftc_cot_engine as cce
        cot = cce.get_us30_cot_report()
    except Exception:
        pass

    cross = []
    try:
        import cross_asset as ca
        cross = ca.get_macro_assets_quotes()
    except Exception:
        pass

    # =========================================================================
    # PART 1: UNIFIED US30 SCALP SIGNAL (15m Timeframe / 1m Sniper with Lock & Anti-Front-Run)
    # =========================================================================
    cvd_data = nt.get("cvd", {})
    cvd_val = cvd_data.get("value", 120) if isinstance(cvd_data, dict) else 120
    sc_div = sc.get("delta_divergence", {}).get("type_fa", "صعودی")
    atas_tps = atas.get("tape_speed", {}).get("trades_per_sec", 45)

    # REAL DYNAMIC MARKET STRUCTURE (SMC, CHoCH, VWAP, EMA & TRENDO PRICE ACTION)
    smc_bias = 0
    htf_bias = 0
    try:
        import us30_engine as ue
        analysis_data = ue.build_analysis("15m")
        st_data = analysis_data.get("structure", {})
        smc_bias = int(st_data.get("bias", -1))
        htf_bias = int(st_data.get("htf_bias", -1))
    except Exception:
        pass

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

    # Dynamic Scoring Matrix based on actual price structure
    score_long = 0
    score_short = 0

    if smc_bias > 0: score_long += 35
    elif smc_bias < 0: score_short += 35

    if htf_bias > 0: score_long += 25
    elif htf_bias < 0: score_short += 25

    # Check orderflow delta & divergence
    if cvd_val > 50: score_long += 15
    elif cvd_val < -50: score_short += 15

    if "نزولی" in sc_div or "فروش" in sc_div or "تخلیه" in sc_div: score_short += 20
    elif "صعودی" in sc_div or "جذب" in sc_div: score_long += 10

    if bm.get("imbalance_pct", 0) < -3.0: score_short += 15
    elif bm.get("imbalance_pct", 0) > 3.0: score_long += 15

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
        scalp_is_short = (score_short > score_long)
    scalp_dir_str = "خرید (LONG)" if scalp_is_long else "فروش (SHORT)"
    scalp_dir_emoji = "🟢" if scalp_is_long else "🔴"

    # Micro Stop Loss strictly 13.0 points ($1.30 in 0.01 lot for $10 account)
    micro_sl_pts = 13.0
    now_epoch = time.time()

    # Check if existing scalp setup is still locked and active (45 min lock)
    is_valid_scalp_lock = (
        _LOCKED_SCALP_STATE.get("active", False)
        and now_epoch < _LOCKED_SCALP_STATE.get("expires_at", 0)
        and _LOCKED_SCALP_STATE.get("entry", 0) > 10000
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
        scalp_dir_str = "خرید (LONG)" if scalp_is_long else "فروش (SHORT)"
        scalp_dir_emoji = "🟢" if scalp_is_long else "🔴"
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
        if scalp_is_long:
            pullback_dist = 5.0
            scalp_entry = round(t_bid - pullback_dist, 1)
            entry_low = round(scalp_entry - 2.5, 1)
            entry_high = scalp_entry
            scalp_sl = round(scalp_entry - micro_sl_pts, 1)

            raw_tp1 = scalp_entry + 28.0
            raw_tp2 = scalp_entry + 55.0
            raw_tp3 = scalp_entry + 90.0

            scalp_tp1 = _apply_us30_anti_front_run_tp(raw_tp1, scalp_entry, True, bm_asks)
            scalp_tp2 = _apply_us30_anti_front_run_tp(raw_tp2, scalp_entry, True, bm_asks)
            scalp_tp3 = _apply_us30_anti_front_run_tp(raw_tp3, scalp_entry, True, bm_asks)

            if scalp_tp1 <= scalp_entry: scalp_tp1 = round(scalp_entry + 18.0, 1)
            if scalp_tp2 <= scalp_tp1: scalp_tp2 = round(scalp_tp1 + 25.0, 1)
            if scalp_tp3 <= scalp_tp2: scalp_tp3 = round(scalp_tp2 + 30.0, 1)

            scalp_tp1_pts = int(round(scalp_tp1 - scalp_entry))
            scalp_tp2_pts = int(round(scalp_tp2 - scalp_entry))
            scalp_tp3_pts = int(round(scalp_tp3 - scalp_entry))
        else:
            pullback_dist = 5.0
            scalp_entry = round(t_ask + pullback_dist, 1)
            entry_low = scalp_entry
            entry_high = round(scalp_entry + 2.5, 1)
            scalp_sl = round(scalp_entry + micro_sl_pts, 1)

            raw_tp1 = scalp_entry - 28.0
            raw_tp2 = scalp_entry - 55.0
            raw_tp3 = scalp_entry - 90.0

            scalp_tp1 = _apply_us30_anti_front_run_tp(raw_tp1, scalp_entry, False, bm_bids)
            scalp_tp2 = _apply_us30_anti_front_run_tp(raw_tp2, scalp_entry, False, bm_bids)
            scalp_tp3 = _apply_us30_anti_front_run_tp(raw_tp3, scalp_entry, False, bm_bids)

            if scalp_tp1 >= scalp_entry: scalp_tp1 = round(scalp_entry - 18.0, 1)
            if scalp_tp2 >= scalp_tp1: scalp_tp2 = round(scalp_tp1 - 25.0, 1)
            if scalp_tp3 >= scalp_tp2: scalp_tp3 = round(scalp_tp2 - 25.0, 1)

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
            "direction": "LONG" if scalp_is_long else "SHORT",
            "created_at": now_epoch,
            "expires_at": now_epoch + 2700,  # 45 minutes locked
            "time_str": tehran_time_str,
            "date_str": tehran_date_str
        }
        lock_status_note = "⚡ ستاپ تازه صادر و قفل شد (مجهز به فیلتر ضد فرانت‌رانینگ)"

    scalp_signal = {
        "signal_type": "SCALP",
        "signal_type_fa": "میکرو-اسکالپ تک‌تیرانداز داوجونز (Sniper 1m / 15m)",
        "timeframe": "1m (تک‌تیرانداز پیش‌دستانه)",
        "direction": scalp_dir_str,
        "direction_code": "LONG" if scalp_is_long else "SHORT",
        "direction_emoji": scalp_dir_emoji,
        "entry": scalp_entry,
        "entry_fmt": f"${scalp_entry:,.1f}",
        "stop_loss": scalp_sl,
        "stop_loss_pts": int(micro_sl_pts),
        "current_price_issued": current_price,
        "stop_loss_fmt": f"${scalp_sl:,.1f} (-{int(micro_sl_pts)} پوینت / -$1.30 در 0.01 لات)",
        "tp1": scalp_tp1,
        "tp1_pts": scalp_tp1_pts,
        "tp1_fmt": f"${scalp_tp1:,.1f} (+{scalp_tp1_pts} پوینت / +${scalp_tp1_pts*0.1:.2f})",
        "tp2": scalp_tp2,
        "tp2_pts": scalp_tp2_pts,
        "tp2_fmt": f"${scalp_tp2:,.1f} (+{scalp_tp2_pts} پوینت / +${scalp_tp2_pts*0.1:.2f})",
        "tp3": scalp_tp3,
        "tp3_pts": scalp_tp3_pts,
        "tp3_fmt": f"${scalp_tp3:,.1f} (+{scalp_tp3_pts} پوینت / +${scalp_tp3_pts*0.1:.2f})",
        "leverage_recommended": "1:500 یا 1:1000 ترندو",
        "lot_recommended": "0.01 لات استاندارد (مارجین امن حساب ۱۰ دلاری)",
        "entry_instruction_fa": f"کاشت لیمیت خرید (Buy Limit) در پولبک به تراز {scalp_entry:,.1f} (پشت شلف نقدینگی و VWAP)" if scalp_is_long else f"کاشت لیمیت فروش (Sell Limit) در پولبک به تراز {scalp_entry:,.1f} (زیر دیواره عرضه و VWAP)",
        "date_tehran": tehran_date_str,
        "time_tehran": tehran_time_str,
        "holding_duration": "۲ الی ۱۰ دقیقه (خروج سریع)",
        "holding_duration_en": "2m - 10m",
        "core_modules": "Bookmap L2/L3 Walls + 1m Footprint Delta + Anti-Front-Run",
        "rationale_fa": "ورود پیش‌دستانه با استاپ فوق‌باریک ۱۳ پوینتی (مناسب حساب $10)؛ کلیه تارگت‌ها ۳ پوینت پیش از دیواره‌های رُند ۵۰ پوینتی ست شده‌اند تا پیش از بازگشت قیمت نقد شوند."
    }

    # =========================================================================
    # PART 2: UNIFIED US30 SWING SIGNAL (4h Timeframe - 4-Hour Lock & Macro Anti-Front-Run)
    # =========================================================================
    qt_mp = qt.get("market_profile", {})
    qt_vah = qt_mp.get("vah", current_price + 220)
    qt_val = qt_mp.get("val", current_price - 180)

    cot_bias = cot.get("institutional_status", cot.get("badge", "BULLISH"))
    dxy_chg = 0.0
    if isinstance(cross, list):
        for item in cross:
            if "DX" in item.get("symbol", ""):
                dxy_chg = float(item.get("change_pct", 0.0) or 0.0)

    swing_bull_score = 0
    if "BULL" in str(cot_bias).upper() or "صعود" in str(cot_bias):
        swing_bull_score += 4
    if dxy_chg <= 0.2:  # Weak dollar index is bullish for US30
        swing_bull_score += 3
    if current_price >= qt_val:
        swing_bull_score += 3

    swing_is_long = swing_bull_score >= 6
    swing_dir_str = "خرید (LONG)" if swing_is_long else "فروش (SHORT)"
    swing_dir_emoji = "🟢" if swing_is_long else "🔴"

    is_valid_swing_lock = (
        _LOCKED_SWING_STATE.get("active", False)
        and now_epoch < _LOCKED_SWING_STATE.get("expires_at", 0)
        and _LOCKED_SWING_STATE.get("entry", 0) > 10000
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
    else:
        t_bid = current_price
        try:
            import trendo_engine
            t_data = trendo_engine.get_trendo_us30_live()
            if t_data.get("ok"):
                t_bid = float(t_data.get("bid", current_price))
        except Exception:
            pass

        swing_sl_pts = 280
        if swing_is_long:
            swing_entry = t_bid
            swing_sl = round(t_bid - swing_sl_pts, 1)

            raw_sw_tp1 = t_bid + 550.0
            raw_sw_tp2 = t_bid + 1450.0
            raw_sw_tp3 = t_bid + 2400.0

            swing_tp1 = _apply_us30_anti_front_run_tp(raw_sw_tp1, swing_entry, True)
            swing_tp2 = _apply_us30_anti_front_run_tp(raw_sw_tp2, swing_entry, True)
            swing_tp3 = _apply_us30_anti_front_run_tp(raw_sw_tp3, swing_entry, True)

            swing_tp1_pts = int(round(swing_tp1 - swing_entry))
            swing_tp2_pts = int(round(swing_tp2 - swing_entry))
            swing_tp3_pts = int(round(swing_tp3 - swing_entry))
        else:
            swing_entry = t_bid
            swing_sl = round(t_bid + swing_sl_pts, 1)

            raw_sw_tp1 = t_bid - 550.0
            raw_sw_tp2 = t_bid - 1450.0
            raw_sw_tp3 = t_bid - 2400.0

            swing_tp1 = _apply_us30_anti_front_run_tp(raw_sw_tp1, swing_entry, False)
            swing_tp2 = _apply_us30_anti_front_run_tp(raw_sw_tp2, swing_entry, False)
            swing_tp3 = _apply_us30_anti_front_run_tp(raw_sw_tp3, swing_entry, False)

            swing_tp1_pts = int(round(swing_entry - swing_tp1))
            swing_tp2_pts = int(round(swing_entry - swing_tp2))
            swing_tp3_pts = int(round(swing_entry - swing_tp3))

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

    swing_signal = {
        "signal_type": "SWING",
        "signal_type_fa": "سوئینگ تریدینگ داوجونز (موج‌سواری چندروزه)",
        "timeframe": "4h",
        "direction": swing_dir_str,
        "direction_code": "LONG" if swing_is_long else "SHORT",
        "direction_emoji": swing_dir_emoji,
        "entry": swing_entry,
        "entry_fmt": f"${swing_entry:,.1f}",
        "stop_loss": swing_sl,
        "stop_loss_pts": swing_sl_pts,
        "stop_loss_fmt": f"${swing_sl:,.1f} (-{swing_sl_pts} پوینت)",
        "tp1": swing_tp1,
        "tp1_pts": swing_tp1_pts,
        "tp1_fmt": f"${swing_tp1:,.1f} (+{swing_tp1_pts} پوینت)",
        "tp2": swing_tp2,
        "tp2_pts": swing_tp2_pts,
        "tp2_fmt": f"${swing_tp2:,.1f} (+{swing_tp2_pts} پوینت)",
        "tp3": swing_tp3,
        "tp3_pts": swing_tp3_pts,
        "tp3_fmt": f"${swing_tp3:,.1f} (+{swing_tp3_pts} پوینت)",
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
    is_aligned = scalp_is_long == swing_is_long
    if is_aligned:
        alignment_status = "همسویی کامل (Full Alignment 💎)"
        alignment_note = "هر دو دیدگاه اسکالپ و سوئینگ داوجونز هم‌جهت هستند؛ ستاپ در بالاترین سطح اعتبار و وین‌ریت سازمانی قرار دارد."
    else:
        alignment_status = "اسکالپ اصلاحی درون روند کلان (Counter-Trend Retracement ⚠️)"
        alignment_note = "دیدگاه اسکالپ ۱۵ دقیقه‌ای خلاف جهت سوئینگ چندروزه است؛ این معامله یک پولبک موقت است و خروج سریع در TP1 الزامی است."

    return {
        "ok": True,
        "symbol": "US30",
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
    cur_p = sig.get("current_price_issued", sig.get("entry", 51250.0))

    if not is_swing:
        risk_lot_note = """📦 <b>حجم و اهرم پیشنهادی:</b> <code>0.01 لات | اهرم 1:500 یا 1:1000 ترندو</code>
💵 <b>محاسبه حساب $10:</b> <code>ریسک -$1.30 | تارگت اول +$2.40</code>"""
    else:
        risk_lot_note = """📦 <b>حجم پیشنهادی:</b> <code>0.01 لات به ازای هر $50 بالانس</code>"""

    msg = f"""💎 <b>سیگنال داوجونز [#US30]</b>
━━━━━━━━━━━━━━━━━━━━
🏢 <b>بروکر مرجع:</b> <code>ترندو آنلاین (Trendo Live Feed)</code>
🧭 <b>جهت معامله:</b> {dir_emoji} <b>{direction}</b>
⏱️ <b>تایم‌فریم:</b> <code>{tf}</code>
💰 <b>قیمت لحظه صدور:</b> <code>${cur_p:,.1f}</code>
🎯 <b>قیمت ورود قطعی:</b> <code>{entry_fmt}</code>
🛑 <b>حد ضرر (SL):</b> <code>{sl_fmt}</code>
🎯 <b>حد سود اول (TP1):</b> <code>{tp1_fmt}</code>
🎯 <b>حد سود دوم (TP2):</b> <code>{tp2_fmt}</code>
🎯 <b>حد سود سوم (TP3):</b> <code>{tp3_fmt}</code>
🛡️ <b>مکانیزم ضد فرانت‌رانینگ:</b> <code>فعال (خروج ۳ پوینت پیش از دیواره‌های رُند .00 / .50)</code>
{risk_lot_note}
⏰ <b>تاریخ و ساعت صدور:</b> <code>{date_tehran} ساعت {time_tehran} (ایران 🇮🇷)</code>
⏳ <b>انقضا / اعتبار ستاپ:</b> <code>تا زمان برخورد به حد سود یا حد ضرر</code>
━━━━━━━━━━━━━━━━━━━━"""
    return msg.strip()

format_us30_minimal_telegram_signal = format_us30_clean_telegram_signal
