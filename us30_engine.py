#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
us30_engine.py — dedicated US30/Dow Jones analysis engine.

This wraps the previous Dow/Gold Smart Money engine inside the ASEMAN-style
FastAPI architecture. The result is deliberately single-asset: US30 only.
"""

from __future__ import annotations

import os
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

import market_data as md
import smart_money as smc

try:
    import dow_cash as dcash
except Exception:  # pragma: no cover
    dcash = None

_CACHE: Dict[str, Dict[str, Any]] = {}
_LOCK = threading.Lock()


def _env(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


def _bool_env(name: str, default: bool = False) -> bool:
    v = _env(name, "true" if default else "false").lower()
    return v in {"1", "true", "yes", "on", "y"}


def _ttl(interval: str) -> int:
    base = {"5m": 70, "15m": 120, "30m": 180, "1h": 300, "1d": 900}.get(interval, 180)
    try:
        return int(_env("CACHE_TTL_SECONDS", str(base)))
    except Exception:
        return base


def _clean(v: Any) -> Any:
    if v is None:
        return None
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating,)):
        f = float(v)
        return None if not np.isfinite(f) else round(f, 6)
    if isinstance(v, (np.bool_, bool)):
        return bool(v)
    if isinstance(v, float):
        return None if not np.isfinite(v) else round(v, 6)
    if isinstance(v, (pd.Timestamp,)):
        return v.isoformat()
    if isinstance(v, datetime):
        return v.isoformat()
    if isinstance(v, np.ndarray):
        return [_clean(x) for x in v.tolist()]
    if isinstance(v, dict):
        return {str(k): _clean(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_clean(x) for x in v]
    return v


def _round_price(x: Optional[float], scale: float, decimals: int = 0) -> Optional[float]:
    if x is None:
        return None
    try:
        y = float(x) * float(scale)
        if not np.isfinite(y):
            return None
        return round(y, decimals)
    except Exception:
        return None


def _round_raw(x: Optional[float], decimals: int = 6) -> Optional[float]:
    if x is None:
        return None
    try:
        y = float(x)
        if not np.isfinite(y):
            return None
        return round(y, decimals)
    except Exception:
        return None


def _fmt_num(x: Optional[float], decimals: int = 0) -> str:
    if x is None:
        return "—"
    try:
        return f"{float(x):,.{decimals}f}"
    except Exception:
        return "—"


def _live_dow_cash() -> Dict[str, Any]:
    """Live US30 price prioritizing TradingView / FOREX.COM live quote, with fallback to cash/futures."""
    # 1. TradingView Live CFD Quote (Matches https://www.tradingview.com/symbols/FOREXCOM-US30/)
    try:
        import urllib.request
        import json
        url = "https://scanner.tradingview.com/cfd/scan"
        payload = {
            "symbols": {"tickers": ["OANDA:US30USD", "FOREXCOM:US30"]},
            "columns": ["close", "change", "change_abs", "high", "low", "open", "volume"]
        }
        req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers={"User-Agent": "Mozilla/5.0", "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=3.0) as resp:
            data = json.loads(resp.read().decode())
            rows = data.get("data", [])
            if rows:
                d = rows[0].get("d", [])
                price = float(d[0])
                chg_pct = float(d[1])
                chg_abs = float(d[2])
                return {
                    "ok": True,
                    "price": round(price, 1),
                    "change": round(chg_abs, 1),
                    "change_pct": round(chg_pct, 2),
                    "mode": "tradingview_live",
                    "source_fa": "زنده تریدینگ‌ویو (FOREXCOM / US30)",
                    "symbol": "FOREXCOM:US30",
                    "checked_at": time.strftime("%Y-%m-%d %H:%M:%S UTC")
                }
    except Exception:
        pass

    # 2. Fallback to cash / futures calculation
    if dcash is not None:
        try:
            return dcash.cash_price(ttl=20.0)
        except Exception:
            pass

    return {"ok": False, "error": "live price unavailable"}


def _apply_live_price(payload: Dict[str, Any]) -> Dict[str, Any]:
    try:
        p = payload.get("price") or {}
        live = _live_dow_cash()
        p["analysis_proxy"] = {
            "last": p.get("last"),
            "open": p.get("open"),
            "high": p.get("high"),
            "low": p.get("low"),
            "change": p.get("change"),
            "change_pct": p.get("change_pct"),
            "source": "DIA × display_scale candles",
        }
        p["live_source"] = live
        if live.get("ok") and live.get("price") is not None:
            last = round(float(live["price"]), 0)
            prev = live.get("prev_close")
            chg = live.get("change")
            chg_pct = live.get("change_pct")
            p["last"] = last
            if prev is not None:
                p["prev_close"] = round(float(prev), 2)
            if chg is not None:
                p["change"] = round(float(chg), 0)
            if chg_pct is not None:
                p["change_pct"] = round(float(chg_pct), 3)
            p["display"] = _fmt_num(last, 0)
            p["source_fa"] = live.get("source_fa")
            p["delay_fa"] = live.get("delay_fa")
            p["basis"] = live.get("basis")
            p["live_symbol"] = live.get("symbol")
            payload["price"] = p
            payload.setdefault("meta", {})["display_price_source"] = "dow_cash: ^DJI or YM=F-basis"
        return payload
    except Exception:
        return payload


def market_state(now: Optional[datetime] = None) -> Dict[str, Any]:
    """NYSE/US index regular session state, with Tehran and New York time."""
    ny = ZoneInfo("America/New_York")
    teh = ZoneInfo("Asia/Tehran")
    utc = timezone.utc
    now_utc = now.astimezone(utc) if now else datetime.now(utc)
    n = now_utc.astimezone(ny)
    t = n.time()
    wd = n.weekday()  # Mon=0
    open_dt = n.replace(hour=9, minute=30, second=0, microsecond=0)
    close_dt = n.replace(hour=16, minute=0, second=0, microsecond=0)
    is_weekday = wd < 5
    is_open = bool(is_weekday and open_dt <= n <= close_dt)

    if is_open:
        next_event = close_dt
        status_fa = "بازار نقدی آمریکا باز است"
    else:
        status_fa = "بازار نقدی آمریکا بسته است"
        # next open: today if before open on weekday, else next weekday
        candidate = open_dt
        if not is_weekday or n >= close_dt:
            d = n + timedelta(days=1)
            while d.weekday() >= 5:
                d += timedelta(days=1)
            candidate = d.replace(hour=9, minute=30, second=0, microsecond=0)
        next_event = candidate

    seconds = max(0, int((next_event - n).total_seconds()))
    return {
        "ok": True,
        "is_open": is_open,
        "status_fa": status_fa,
        "market": "NYSE / Dow Jones regular cash session",
        "new_york_time": n.strftime("%Y-%m-%d %H:%M"),
        "tehran_time": now_utc.astimezone(teh).strftime("%Y-%m-%d %H:%M"),
        "session_hours_tehran_note": "تقریباً ۱۷:۰۰ تا ۲۳:۳۰ تهران؛ با DST آمریکا ممکن است تغییر کند.",
        "next_event_new_york": next_event.strftime("%Y-%m-%d %H:%M"),
        "next_event_tehran": next_event.astimezone(teh).strftime("%Y-%m-%d %H:%M"),
        "seconds_to_next_event": seconds,
    }


def _last(series: Any) -> Optional[float]:
    try:
        if hasattr(series, "iloc"):
            return float(series.iloc[-1])
        return float(series[-1])
    except Exception:
        return None


def _candles(df: pd.DataFrame, bars: int, scale: float, decimals: int) -> List[Dict[str, Any]]:
    d = df.tail(max(20, min(int(bars), 600)))
    out = []
    for i, r in d.iterrows():
        out.append({
            "t": pd.Timestamp(i).isoformat(),
            "o": _round_price(r.Open, scale, decimals),
            "h": _round_price(r.High, scale, decimals),
            "l": _round_price(r.Low, scale, decimals),
            "c": _round_price(r.Close, scale, decimals),
            "v": _round_raw(r.Volume, 2),
        })
    return out


def _scale_plan(plan: Dict[str, Any], scale: float, decimals: int) -> Dict[str, Any]:
    if not isinstance(plan, dict) or not plan:
        return {}
    out = dict(plan)
    for k in ("entry", "stop", "tp1", "tp2", "tp3", "risk"):
        if k in out:
            out[k] = _round_price(out[k], scale, decimals)
    for k in ("rr1", "rr2", "rr3", "risk_pct"):
        if k in out:
            out[k] = _round_raw(out[k], 3)
    return out


def _signal_block(sig: Dict[str, Any], scale: float, decimals: int) -> Dict[str, Any]:
    parts = []
    for p in sig.get("parts", [])[:18]:
        try:
            name, weight, detail = p[0], p[1], p[2]
        except Exception:
            continue
        parts.append({"name": str(name), "weight": _round_raw(weight, 2), "detail": str(detail)})
    plan = _scale_plan(sig.get("plan", {}) or {}, scale, decimals)
    return {
        "direction": int(sig.get("direction", 0) or 0),
        "label": sig.get("label", "خنثی"),
        "grade": sig.get("grade", "D"),
        "score": _round_raw(sig.get("score"), 2),
        "raw_score": _round_raw(sig.get("raw_score"), 2),
        "confidence": _round_raw(sig.get("confidence"), 1),
        "fake_penalty": _round_raw(sig.get("fake_penalty"), 3),
        "hft_penalty": _round_raw(sig.get("hft_penalty"), 3),
        "price": _round_price(sig.get("price"), scale, decimals),
        "atr": _round_price(sig.get("atr"), scale, decimals),
        "plan": plan,
        "parts": parts,
        "verdict_fa": _verdict(sig),
    }


def _verdict(sig: Dict[str, Any]) -> str:
    direction = int(sig.get("direction", 0) or 0)
    conf = float(sig.get("confidence", 0) or 0)
    if direction == 0 or conf < 33:
        return "فعلاً ستاپ قطعی نداریم؛ منتظر تایید ساختار و شکست معتبر بمانید."
    if direction > 0:
        return "سوگیری فعلی لانگ است؛ ورود فقط نزدیک ناحیه پیشنهادی و با رعایت حد ضرر."
    return "سوگیری فعلی شورت است؛ ورود فقط با تایید شکست/بازگشت و مدیریت ریسک."


def _structure_block(res: Dict[str, Any], df: pd.DataFrame, scale: float, decimals: int) -> Dict[str, Any]:
    n = len(df)
    events = []
    for e in (res.get("struct", {}) or {}).get("events", [])[-18:]:
        events.append({
            "time": _clean(e.get("time")),
            "type": e.get("type"),
            "dir": e.get("dir"),
            "level": _round_price(e.get("level"), scale, decimals),
            "price": _round_price(e.get("price"), scale, decimals),
            "age_bars": int(n - 1 - e.get("i", n - 1)) if isinstance(e.get("i"), (int, np.integer)) else None,
        })
    return {
        "bias": int((res.get("struct", {}) or {}).get("bias", 0) or 0),
        "htf_bias": res.get("htf_bias"),
        "events": events,
    }


def _fvg_block(res: Dict[str, Any], df: pd.DataFrame, scale: float, decimals: int) -> List[Dict[str, Any]]:
    price = float(df["Close"].iloc[-1])
    out = []
    for g in res.get("fvgs", []) or []:
        if g.get("filled"):
            continue
        mid = (float(g.get("top", 0)) + float(g.get("bottom", 0))) / 2
        out.append({
            "time": _clean(g.get("time")),
            "dir": g.get("dir"),
            "top": _round_price(g.get("top"), scale, decimals),
            "bottom": _round_price(g.get("bottom"), scale, decimals),
            "atr_x": _round_raw(g.get("atr_x"), 2),
            "dist_pct": _round_raw((mid - price) / price * 100 if price else None, 2),
            "mitigated": bool(g.get("mitigated")),
        })
    return sorted(out, key=lambda x: abs(x.get("dist_pct") or 999))[:14]


def _order_blocks(res: Dict[str, Any], df: pd.DataFrame, scale: float, decimals: int) -> List[Dict[str, Any]]:
    price = float(df["Close"].iloc[-1])
    out = []
    for b in res.get("obs", []) or []:
        if b.get("mitigated"):
            continue
        mid = (float(b.get("top", 0)) + float(b.get("bottom", 0))) / 2
        out.append({
            "time": _clean(b.get("time")),
            "dir": b.get("dir"),
            "top": _round_price(b.get("top"), scale, decimals),
            "bottom": _round_price(b.get("bottom"), scale, decimals),
            "disp_atr": _round_raw(b.get("disp_atr"), 2),
            "vol_z": _round_raw(b.get("vol_z"), 2),
            "dist_pct": _round_raw((mid - price) / price * 100 if price else None, 2),
        })
    return sorted(out, key=lambda x: abs(x.get("dist_pct") or 999))[:12]


def _liquidity_block(res: Dict[str, Any], scale: float, decimals: int) -> Dict[str, Any]:
    liq = res.get("liq", {}) or {}

    def lvl(x: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "price": _round_price(x.get("price"), scale, decimals),
            "hits": x.get("hits"),
            "kind": x.get("kind"),
            "dist_pct": _round_raw(x.get("dist_pct"), 2),
            "eq": bool(x.get("eq", False)),
        }

    periodic = {}
    for k, v in (liq.get("periodic") or {}).items():
        periodic[k] = {
            "high": _round_price(v.get("high"), scale, decimals),
            "low": _round_price(v.get("low"), scale, decimals),
        }
    return {
        "bsl": [lvl(x) for x in (liq.get("fresh_bsl") or [])[:8]],
        "ssl": [lvl(x) for x in (liq.get("fresh_ssl") or [])[:8]],
        "periodic": periodic,
        "tolerance": _round_price(liq.get("tol"), scale, decimals),
    }


def _volume_profile(res: Dict[str, Any], scale: float, decimals: int) -> Dict[str, Any]:
    vp = res.get("vprof") or {}
    if not vp:
        return {}
    bins = []
    centers = vp.get("centers")
    profile = vp.get("profile")
    if centers is None:
        centers = []
    if profile is None:
        profile = []
    # Keep the chart payload compact.
    if len(centers) and len(profile):
        step = max(1, len(centers) // 36)
        for p, v in zip(centers[::step], profile[::step]):
            bins.append({"price": _round_price(p, scale, decimals), "vol": _round_raw(v, 2)})
    return {
        "poc": _round_price(vp.get("poc"), scale, decimals),
        "vah": _round_price(vp.get("vah"), scale, decimals),
        "val": _round_price(vp.get("val"), scale, decimals),
        "in_value": bool(vp.get("in_value", False)),
        "poc_dist_pct": _round_raw(vp.get("poc_dist_pct"), 2),
        "near_hvn": _round_price(vp.get("near_hvn"), scale, decimals),
        "near_lvn": _round_price(vp.get("near_lvn"), scale, decimals),
        "hvn": [_round_price(x, scale, decimals) for x in (vp.get("hvn") or [])[:8]],
        "lvn": [_round_price(x, scale, decimals) for x in (vp.get("lvn") or [])[:8]],
        "bins": bins,
    }


def _flow_block(res: Dict[str, Any], scale: float, decimals: int) -> Dict[str, Any]:
    fl = res.get("flow") or {}
    return {
        "vwap": _round_price(fl.get("vwap"), scale, decimals),
        "vwap_dev_pct": _round_raw(fl.get("vwap_dev_pct"), 2),
        "cd_slope": _round_raw(fl.get("cd_slope"), 4),
        "obv_slope": _round_raw(fl.get("obv_slope"), 4),
        "ad_slope": _round_raw(fl.get("ad_slope"), 4),
        "cmf": _round_raw(fl.get("cmf_last"), 4),
        "mfi": _round_raw(fl.get("mfi_last"), 1),
        "divergence": fl.get("divergence"),
        "smi_trend": _round_raw(fl.get("smi_trend"), 4),
        "price_chg_pct": _round_raw(fl.get("price_chg_pct"), 2),
        "cd_chg": _round_raw(fl.get("cd_chg"), 2),
    }


def _hft_fake_block(res: Dict[str, Any], scale: float, decimals: int) -> Dict[str, Any]:
    hft = res.get("hft") or {}
    fake = res.get("fake") or {}

    def ev(x: Dict[str, Any]) -> Dict[str, Any]:
        y = dict(x)
        for k in ("price", "level", "current_price", "extreme", "reached", "closed", "overshoot"):
            if k in y:
                y[k] = _round_price(y[k], scale, decimals)
        return _clean(y)

    def as_list(value: Any) -> List[Any]:
        return value if isinstance(value, list) else []

    return {
        "hft": {
            "hft_index": _round_raw(hft.get("hft_index"), 1),
            "regime": hft.get("regime"),
            "burst_rate": _round_raw(hft.get("burst_rate"), 4),
            "hunt_rate": _round_raw(hft.get("hunt_rate"), 4),
            "pin_rate": _round_raw(hft.get("pin_rate"), 4),
            "n_absorb": hft.get("n_absorb"),
            "n_hunt": hft.get("n_hunt"),
            "absorb_events": [ev(x) for x in as_list(hft.get("absorb_events"))[:8]],
            "hunt_events": [ev(x) for x in as_list(hft.get("hunt_events"))[:8]],
        },
        "fake": {
            "score": _round_raw(fake.get("score"), 1),
            "verdict": fake.get("verdict"),
            "reasons": as_list(fake.get("reasons"))[:8],
            "watch_levels": [ev(x) for x in as_list(fake.get("watch_levels"))[:8]],
            "fake_break_count": fake.get("fake_breaks") if isinstance(fake.get("fake_breaks"), (int, float)) else None,
            "fake_breaks": [ev(x) for x in as_list(fake.get("fake_levels"))[:8]],
        },
    }


def _sweeps_blocks(res: Dict[str, Any], scale: float, decimals: int) -> Dict[str, Any]:
    sweeps = []
    for s in (res.get("sweeps") or [])[-14:]:
        sweeps.append({
            "time": _clean(s.get("time")),
            "type": s.get("type"),
            "dir": s.get("dir"),
            "level": _round_price(s.get("level"), scale, decimals),
            "extreme": _round_price(s.get("extreme"), scale, decimals),
            "depth_atr": _round_raw(s.get("depth_atr"), 2),
            "wick": _round_raw(s.get("wick"), 3),
            "vol_z": _round_raw(s.get("vol_z"), 2),
        })
    blocks_raw = res.get("blocks") or {}
    block_items = []
    for b in (blocks_raw.get("blocks") or [])[-12:]:
        block_items.append({
            "time": _clean(b.get("time")),
            "side": b.get("side"),
            "price": _round_price(b.get("price"), scale, decimals),
            "vol_z": _round_raw(b.get("vol_z"), 2),
            "ret_pct": _round_raw(b.get("ret_pct"), 3),
            "notional": _round_raw(b.get("notional"), 2),
        })
    return {
        "sweeps": sweeps,
        "blocks": {
            "n": blocks_raw.get("n_blocks", 0),
            "imbalance": _round_raw(blocks_raw.get("imbalance"), 3),
            "buy_notional": _round_raw(blocks_raw.get("buy_notional"), 2),
            "sell_notional": _round_raw(blocks_raw.get("sell_notional"), 2),
            "items": block_items,
        },
    }


def _coalition_block(res: Dict[str, Any]) -> Dict[str, Any]:
    c = res.get("coalition") or {}
    return {
        "ok": bool(c.get("ok")),
        "score": _round_raw(c.get("score"), 3),
        "agreement": _round_raw(c.get("agreement"), 3),
        "heavy": _round_raw(c.get("heavy"), 3),
        "corr": _round_raw(c.get("corr"), 3),
        "basket_fa": c.get("basket_fa"),
        "members": _clean((c.get("members") or [])[:8]),
        "error": c.get("error"),
    }


def _position_sizing(plan: Dict[str, Any], equity: float, risk_pct: float) -> Dict[str, Any]:
    try:
        entry = float(plan.get("entry") or 0)
        stop = float(plan.get("stop") or 0)
        risk_unit = abs(entry - stop)
        if entry <= 0 or risk_unit <= 0 or equity <= 0 or risk_pct <= 0:
            return {"ok": False, "note": "برای سایزینگ، پلن معتبر لازم است."}
        risk_amount = equity * risk_pct / 100
        units = risk_amount / risk_unit
        notional = units * entry
        return {
            "ok": True,
            "equity": round(equity, 2),
            "risk_pct": round(risk_pct, 3),
            "risk_amount": round(risk_amount, 2),
            "risk_per_unit": round(risk_unit, 2),
            "units": round(units, 4),
            "notional": round(notional, 2),
            "note": "محاسبه آموزشی است؛ با مشخصات قرارداد بروکر خود تطبیق دهید.",
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


def build_analysis(
    interval: str = "1h",
    bars: int = 180,
    force: bool = False,
    with_coalition: Optional[bool] = None,
    equity: float = 10_000,
    risk_pct: float = 1.0,
) -> Dict[str, Any]:
    interval = interval if interval in md.VALID_INTERVALS else _env("DEFAULT_INTERVAL", "1h")
    bars = max(80, min(int(bars or 180), 600))
    if with_coalition is None:
        with_coalition = _bool_env("WITH_COALITION", True)

    key = f"{interval}:{bars}:{int(with_coalition)}:{md.selected_provider()}:{md.selected_symbol()}:{md.display_scale_for()}"
    now = time.time()
    if not force:
        with _LOCK:
            hit = _CACHE.get(key)
            if hit and now - hit["ts"] < _ttl(interval):
                data = dict(hit["data"])
                data["meta"] = dict(data["meta"])
                data["meta"]["cached"] = True
                data["meta"]["age"] = int(now - hit["ts"])
                return _apply_live_price(data)

    fetched = md.fetch_ohlcv(interval, bars)
    df = fetched.df
    if len(df) < 80:
        raise RuntimeError("داده کافی برای تحلیل SMC موجود نیست")

    # Higher timeframe and intraday references use the same provider layer where possible.
    htf_df = None
    intraday = None
    try:
        if interval == "1d":
            htf_df = md.fetch_ohlcv("1d", 300).df.resample("W").agg({
                "Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"
            }).dropna()
            intraday = md.fetch_ohlcv("30m", 260).df
        else:
            htf_df = md.fetch_ohlcv("1d", 420).df
            intraday = df
    except Exception:
        pass

    t0 = time.time()
    res = smc.run_full_smc(
        df,
        interval=interval,
        htf_df=htf_df,
        intraday=intraday,
        with_coalition=bool(with_coalition),
        asset="US30",
    )

    scale = float(fetched.display_scale or 1.0)
    decimals = 0 if scale >= 50 else 2
    close = df["Close"]
    price = float(close.iloc[-1])
    prev = float(close.iloc[-2]) if len(close) > 1 else price
    rsi = smc._rsi(close.to_numpy(float))
    atr = smc.atr_array(df)
    sma20 = close.rolling(20).mean()
    sma50 = close.rolling(50).mean()
    ema200 = close.ewm(span=200, adjust=False).mean()

    signal = _signal_block(res.get("signal", {}) or {}, scale, decimals)
    payload: Dict[str, Any] = {
        "ok": True,
        "meta": {
            "asset": "US30",
            "asset_name": "داوجونز / Dow Jones Industrial Average",
            "architecture": "ASEMAN FastAPI single-service + US30 Smart Money Engine",
            "interval": interval,
            "bars": min(bars, len(df)),
            "provider": fetched.provider,
            "symbol": fetched.symbol,
            "source_note": fetched.source_note,
            "display_scale": scale,
            "raw_price_is_index": fetched.raw_price_is_index,
            "generated": datetime.now(timezone.utc).isoformat(),
            "elapsed": round(time.time() - t0, 2),
            "cached": False,
            "age": 0,
            "first": pd.Timestamp(df.index[-min(bars, len(df))]).isoformat(),
            "last": pd.Timestamp(df.index[-1]).isoformat(),
        },
        "market": market_state(),
        "price": {
            "last": _round_price(price, scale, decimals),
            "open": _round_price(df["Open"].iloc[-1], scale, decimals),
            "high": _round_price(df["High"].iloc[-1], scale, decimals),
            "low": _round_price(df["Low"].iloc[-1], scale, decimals),
            "change": _round_price(price - prev, scale, decimals),
            "change_pct": _round_raw((price - prev) / prev * 100 if prev else 0, 2),
            "volume": _round_raw(df["Volume"].iloc[-1], 2),
            "display": f"{_fmt_num(_round_price(price, scale, decimals), decimals)}",
        },
        "indicators": {
            "rsi": _round_raw(_last(rsi), 1),
            "atr": _round_price(_last(atr), scale, decimals),
            "sma20": _round_price(_last(sma20), scale, decimals),
            "sma50": _round_price(_last(sma50), scale, decimals),
            "ema200": _round_price(_last(ema200), scale, decimals),
            "trend": "صعودی" if _last(sma20) and _last(sma50) and _last(sma20) > _last(sma50) else "نزولی",
        },
        "signal": signal,
        "position_sizing": _position_sizing(signal.get("plan", {}), float(equity), float(risk_pct)),
        "candles": _candles(df, bars, scale, decimals),
        "structure": _structure_block(res, df, scale, decimals),
        "fvgs": _fvg_block(res, df, scale, decimals),
        "order_blocks": _order_blocks(res, df, scale, decimals),
        "liquidity": _liquidity_block(res, scale, decimals),
        "volume_profile": _volume_profile(res, scale, decimals),
        "flow": _flow_block(res, scale, decimals),
        "coalition": _coalition_block(res),
    }
    payload.update(_hft_fake_block(res, scale, decimals))
    payload.update(_sweeps_blocks(res, scale, decimals))

    payload = _clean(_apply_live_price(payload))
    with _LOCK:
        _CACHE[key] = {"ts": time.time(), "data": payload}
    return payload


def ticker(interval: str = "1h") -> Dict[str, Any]:
    fetched = md.fetch_ohlcv(interval if interval in md.VALID_INTERVALS else "1h", 100)
    df = fetched.df
    scale = fetched.display_scale
    decimals = 0 if scale >= 50 else 2
    last = float(df["Close"].iloc[-1])
    prev = float(df["Close"].iloc[-2]) if len(df) > 1 else last
    proxy_price = _round_price(last, scale, decimals)
    proxy_change = _round_price(last - prev, scale, decimals)
    proxy_change_pct = _round_raw((last - prev) / prev * 100 if prev else 0, 2)
    live = _live_dow_cash()
    price = proxy_price
    change = proxy_change
    change_pct = proxy_change_pct
    if live.get("ok") and live.get("price") is not None:
        price = round(float(live["price"]), 0)
        if live.get("change") is not None:
            change = round(float(live["change"]), 0)
        if live.get("change_pct") is not None:
            change_pct = round(float(live["change_pct"]), 3)
    return _clean({
        "ok": True,
        "asset": "US30",
        "symbol": fetched.symbol,
        "provider": fetched.provider,
        "source_note": fetched.source_note,
        "price": price,
        "change": change,
        "change_pct": change_pct,
        "time": pd.Timestamp(df.index[-1]).isoformat(),
        "market": market_state(),
        "live_source": live,
        "analysis_proxy": {"price": proxy_price, "change": proxy_change, "change_pct": proxy_change_pct, "source": "DIA × display_scale"},
    })


def candles(interval: str = "1h", bars: int = 180) -> Dict[str, Any]:
    fetched = md.fetch_ohlcv(interval if interval in md.VALID_INTERVALS else "1h", bars)
    scale = fetched.display_scale
    decimals = 0 if scale >= 50 else 2
    return _clean({
        "ok": True,
        "meta": {
            "asset": "US30", "interval": interval, "bars": bars,
            "provider": fetched.provider, "symbol": fetched.symbol,
            "display_scale": scale,
        },
        "candles": _candles(fetched.df, bars, scale, decimals),
    })
