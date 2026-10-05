#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
execution_guard.py — practical broker/account guard for US30.

It translates the extracted Dow reference into an execution decision:
- validated timeframe/score gate from signal_filter.py
- Trendo margin math for a small account
- spread window estimation
- risk per 0.01 lot from the active plan
- market-hours blocker

This is not financial advice; it is a mechanical risk checker.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional
from zoneinfo import ZoneInfo

import numpy as np

import market_hours
import signal_filter
import us30_reference_config as refcfg

try:
    import validated
except Exception:  # pragma: no cover
    validated = None

TEH = ZoneInfo("Asia/Tehran")
BAD_INTERVALS = set(refcfg.ENGINE_CONSTANTS["bad_intervals"])


def _f(x: Any, default: float = 0.0) -> float:
    try:
        v = float(x)
        return v if np.isfinite(v) else default
    except Exception:
        return default


def _round(x: Any, d: int = 2) -> Optional[float]:
    try:
        f = float(x)
        if not np.isfinite(f):
            return None
        return round(f, d)
    except Exception:
        return None


def current_spread_profile(ts: Optional[datetime] = None) -> Dict[str, Any]:
    now = (ts or datetime.now(TEH)).astimezone(TEH)
    h = now.hour + now.minute / 60.0 + now.second / 3600.0
    # User reference: Trendo is cheapest during the NY session 17:00–23:00 Tehran;
    # the hourly profile still shows 23:00 as cheap, so use 17:00–23:30.
    cheap = 17.0 <= h < 23.5
    spread = refcfg.BROKER_TRENDO["spreads_points"]["ny_session_tehran_17_23"] if cheap else refcfg.BROKER_TRENDO["spreads_points"]["other_hours"]
    zone = "NY_CHEAP_SPREAD" if cheap else "WIDE_SPREAD"
    return {
        "ok": True,
        "tehran_time": now.strftime("%Y-%m-%d %H:%M:%S"),
        "hour_float": round(h, 3),
        "zone": zone,
        "spread_points": spread,
        "spread_fa": f"{spread:.2f} واحد",
        "note_fa": "پنجره ارزان ترِندو / نیویورک" if cheap else "خارج از پنجره ارزان؛ اسپرد حدود ۳ برابر می‌شود",
    }


def broker_margin(price: float, balance: float = 10.0, leverage: float = 50.0, lot: float = 0.01) -> Dict[str, Any]:
    price = max(1.0, _f(price, 50844.0))
    balance = max(0.0, _f(balance, 10.0))
    leverage = max(1.0, _f(leverage, 50.0))
    lot = max(0.0, _f(lot, 0.01))
    per_point = float(refcfg.CONTRACT["US30"]["per_point"])
    notional = price * per_point * lot
    margin = notional / leverage if leverage else notional
    shortage = max(0.0, margin - balance)
    max_lot_by_margin = (balance * leverage) / max(price * per_point, 1e-9)
    return {
        "ok": True,
        "price": round(price, 2),
        "balance_usd": round(balance, 2),
        "leverage": round(leverage, 2),
        "lot": round(lot, 4),
        "per_point_per_1lot_usd": per_point,
        "point_value_usd": round(per_point * lot, 4),
        "notional_usd": round(notional, 2),
        "required_margin_usd": round(margin, 2),
        "margin_shortage_usd": round(shortage, 2),
        "can_open": shortage <= 1e-9,
        "max_lot_by_margin": round(max_lot_by_margin, 4),
        "min_balance_for_this_lot_usd": round(margin, 2),
    }


def plan_risk(plan: Dict[str, Any], balance: float = 10.0, lot: float = 0.01) -> Dict[str, Any]:
    entry = _f(plan.get("entry"), 0.0) if isinstance(plan, dict) else 0.0
    stop = _f(plan.get("stop"), 0.0) if isinstance(plan, dict) else 0.0
    if entry <= 0 or stop <= 0:
        return {"ok": False, "error": "پلن معتبر Entry/Stop ندارد"}
    stop_points = abs(entry - stop)
    point_value = refcfg.CONTRACT["US30"]["per_point"] * max(0.0, _f(lot, 0.01))
    risk_usd = stop_points * point_value
    balance = max(0.01, _f(balance, 10.0))
    risk_pct = risk_usd / balance * 100.0
    account_for_2pct = risk_usd / 0.02 if risk_usd > 0 else None
    return {
        "ok": True,
        "entry": round(entry, 2),
        "stop": round(stop, 2),
        "stop_points": round(stop_points, 2),
        "lot": round(_f(lot, 0.01), 4),
        "point_value_usd": round(point_value, 4),
        "risk_usd": round(risk_usd, 2),
        "risk_pct_of_balance": round(risk_pct, 2),
        "account_needed_for_2pct_risk_usd": round(account_for_2pct, 2) if account_for_2pct else None,
    }


def evaluate(
    analysis: Optional[Dict[str, Any]] = None,
    interval: str = "1h",
    balance: float = 10.0,
    leverage: float = 50.0,
    lot: float = 0.01,
) -> Dict[str, Any]:
    analysis = analysis or {}
    sig = analysis.get("signal", {}) if isinstance(analysis, dict) else {}
    price_block = analysis.get("price", {}) if isinstance(analysis, dict) else {}
    price = _f(price_block.get("last") or sig.get("price"), refcfg.BROKER_TRENDO["account_example"]["price_reference"])
    score = _f(sig.get("score") or sig.get("raw_score"), 0.0)
    direction = int(sig.get("direction") or 0)
    grade = sig.get("grade")
    plan = sig.get("plan", {}) if isinstance(sig, dict) else {}

    blockers = []
    warnings = []
    positives = []

    # Market hours
    mh = market_hours.market_status()
    if not mh.get("is_open"):
        blockers.append(f"بازار نقدی آمریکا بسته است ({mh.get('label') or mh.get('phase')})")
    else:
        positives.append("بازار نقدی آمریکا باز است")

    # Validated quality gate
    # Important trap from the reference: threshold=32 belongs to validated.py,
    # not to every other score scale. Intraday frames are blocked outright; for
    # daily we try to use the validated engine score, then fall back safely.
    interval_bad = interval in BAD_INTERVALS
    validated_payload = None
    q_score = score
    q_source = "analysis_signal_fallback"
    if interval_bad:
        q = {
            "ok": True,
            "asset": "US30",
            "score": round(score, 2),
            "tradeable": False,
            "tier": "rejected_timeframe",
            "tier_fa": "⛔ تایم‌فریم نامناسب",
            "reason": "این تایم‌فریم برای سیگنال مستقل در بک‌تست زیان‌ده بوده؛ فقط برای timing استفاده شود.",
            "score_source": "timeframe_gate",
        }
        blockers.append(q["reason"])
    else:
        if validated is not None:
            try:
                validated_payload = validated.cached(asset="US30", interval="1d")
                if validated_payload.get("ok") and validated_payload.get("score") is not None:
                    q_score = _f(validated_payload.get("score"), score)
                    q_source = "validated.py"
            except Exception as e:
                warnings.append(f"validated.py در دسترس نبود؛ quality gate با احتیاط fallback شد: {str(e)[:80]}")
        q = signal_filter.assess("US30", q_score, "1d")
        q["score_source"] = q_source
        if validated_payload is not None:
            q["validated_payload"] = validated_payload
        if q_source != "validated.py":
            blockers.append("امتیاز معتبر validated.py در دسترس نیست؛ طبق تله مقیاس score، ورود واقعی تأیید نمی‌شود.")
        elif not q.get("tradeable"):
            blockers.append(q.get("reason") or "سیگنال زیر آستانه معتبر است")
        elif q.get("tier") == "acceptable":
            warnings.append(q.get("reason") or "سیگنال قابل قبول ولی نه قوی")
        else:
            positives.append(q.get("reason") or "سیگنال از quality gate عبور کرد")

    # Direction/plan
    if direction == 0:
        blockers.append("جهت سیگنال خنثی است")
    if not plan or not plan.get("entry") or not plan.get("stop"):
        blockers.append("پلن Entry/Stop فعال نیست")

    # Broker margin and risk
    bm = broker_margin(price, balance, leverage, lot)
    if not bm["can_open"]:
        blockers.append(f"مارجین کافی نیست؛ کسری حدود ${bm['margin_shortage_usd']:.2f}")
    pr = plan_risk(plan, balance, lot) if plan else {"ok": False, "error": "no plan"}
    if pr.get("ok"):
        if pr["risk_pct_of_balance"] > 5.0:
            blockers.append(f"ریسک حدضرر برای {lot} لات حدود {pr['risk_pct_of_balance']:.1f}٪ حساب است؛ برای حساب کوچک بسیار زیاد است.")
        elif pr["risk_pct_of_balance"] > 2.0:
            warnings.append(f"ریسک حدضرر بالاتر از ۲٪ حساب است ({pr['risk_pct_of_balance']:.1f}٪).")
    else:
        warnings.append(pr.get("error") or "ریسک پلن قابل محاسبه نیست")

    # Spread quality
    spread = current_spread_profile()
    if spread["zone"] == "WIDE_SPREAD":
        warnings.append("خارج از پنجره ارزان ترِندو هستیم؛ اسپرد حدود ۲.۱۰ واحد است.")
    else:
        positives.append("در پنجره ارزان اسپرد ترِندو هستیم.")
    if pr.get("ok") and pr.get("stop_points"):
        spread_to_stop_pct = spread["spread_points"] / max(pr["stop_points"], 1e-9) * 100.0
        spread["spread_to_stop_pct"] = round(spread_to_stop_pct, 2)
        if spread_to_stop_pct >= 15:
            blockers.append(f"اسپرد نسبت به حدضرر زیاد است ({spread_to_stop_pct:.1f}٪).")
        elif spread_to_stop_pct >= 8:
            warnings.append(f"اسپرد نسبت به حدضرر قابل توجه است ({spread_to_stop_pct:.1f}٪).")

    # DXY trap note
    warnings.append("یادآوری: DXY برای داوجونز وتوی جهت‌دار نیست؛ r=-0.012 و t=-0.27، وزن ۰.")

    allowed = len(blockers) == 0
    status = "✅ مجاز طبق گارد اجرایی" if allowed else "⛔ ورود ممنوع طبق گارد اجرایی"
    color = "GREEN" if allowed else "RED"
    if allowed and warnings:
        status = "⚠️ مجاز با احتیاط"
        color = "YELLOW"

    return {
        "ok": True,
        "asset": "US30",
        "interval": interval,
        "trade_allowed": allowed,
        "status_fa": status,
        "badge_color": color,
        "direction": direction,
        "grade": grade,
        "score": round(score, 2),
        "quality_gate": q,
        "market_hours": mh,
        "spread": spread,
        "broker_margin": bm,
        "plan_risk": pr,
        "blockers": blockers,
        "warnings": warnings,
        "positives": positives,
        "reference": {
            "best_r_us30": refcfg.ENGINE_CONSTANTS["best_r"]["US30"],
            "minimum_score": refcfg.ENGINE_CONSTANTS["threshold"]["US30"]["minimum"],
            "strong_score": refcfg.ENGINE_CONSTANTS["threshold"]["US30"]["strong"],
            "ny_first_15m_range_percentiles": refcfg.US30_MEASURED_NUMBERS["ny_first_15m_range_percentiles"],
        },
    }
