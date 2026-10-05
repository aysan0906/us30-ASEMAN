#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
dow_analyzer_resources.py

Wrapper layer around the useful Dow/US30 modules extracted from:
https://github.com/Tanha2419/dow-analyzer1.git

The original project was Flask-based and multi-endpoint. This file exposes its
useful Dow-specific resources safely inside the current single FastAPI/Render
project without forcing every heavy layer to run on page load.
"""

from __future__ import annotations

import importlib
import json
import time
from pathlib import Path
from typing import Any, Callable, Dict, Optional

import numpy as np
import pandas as pd

import us30_reference_config as refcfg

APP_DIR = Path(__file__).resolve().parent
_CACHE: Dict[str, tuple] = {}


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
    if isinstance(v, np.ndarray):
        return [_clean(x) for x in v.tolist()]
    if isinstance(v, dict):
        return {str(k): _clean(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_clean(x) for x in v]
    return v


def _cached(key: str, ttl: float, fn: Callable[[], Dict[str, Any]]) -> Dict[str, Any]:
    now = time.time()
    hit = _CACHE.get(key)
    if hit and now - hit[0] < ttl:
        out = dict(hit[1]) if isinstance(hit[1], dict) else {"data": hit[1]}
        out["_cache_age"] = round(now - hit[0], 1)
        return out
    out = fn()
    _CACHE[key] = (now, out)
    return out


def _safe(name: str, fn: Callable[[], Any]) -> Dict[str, Any]:
    try:
        data = fn()
        if isinstance(data, dict):
            data = _clean(data)
            # Preserve the module's ok flag if it has one.
            return data if ("ok" in data or "success" in data) else {"ok": True, **data}
        return {"ok": True, "data": _clean(data)}
    except Exception as e:
        return {"ok": False, "source": name, "error": str(e)[:300]}


def _m(module_name: str):
    return importlib.import_module(module_name)


EXTRACTED_MODULES = [
    {
        "file": "assets.py",
        "use": "US30 asset profile: DIA candles, DIA options, display_scale=100, intermarket peers, veto rules, aliases.",
        "integrated_as": "profile(), /api/dow/profile",
    },
    {
        "file": "dow_cash.py",
        "use": "^DJI cash price vs YM=F futures and DIA×factor; live basis calculation for platform-like Dow price.",
        "integrated_as": "cash_price(), /api/dow/cash",
    },
    {
        "file": "market_hours.py",
        "use": "NYSE sessions, pre/regular/post market, half-days, US holidays, Tehran killzones.",
        "integrated_as": "hours(), /api/dow/hours",
    },
    {
        "file": "market_context.py",
        "use": "Multi-timeframe bias, intermarket DXY/US10Y/SPX/NDX/VIX, economic calendar, sentiment, trade gate.",
        "integrated_as": "context(), /api/dow/context",
    },
    {
        "file": "institutional.py",
        "use": "Intermarket veto, institutional feature vector, reference levels, liquidation map, news window, FedWatch proxy.",
        "integrated_as": "institutional module available + used by agent/layers",
    },
    {
        "file": "orderflow.py",
        "use": "CVD/delta proxy, block trades, seasonality, intraday seasonality, candle and chart patterns.",
        "integrated_as": "orderflow(), /api/dow/orderflow",
    },
    {
        "file": "regime_ai.py",
        "use": "Hurst, Kalman trend, ADX regime, WaveTrend, divergences, SuperTrend, Chandelier Exit, anomaly/ML forecast.",
        "integrated_as": "intelligence(), /api/dow/intelligence",
    },
    {
        "file": "volatility.py",
        "use": "DIA options, real Put/Call, IV, skew, VIX9D/VIX/VIX3M structure, historical volatility.",
        "integrated_as": "volatility(), /api/dow/volatility",
    },
    {
        "file": "real_data.py",
        "use": "FOMC/FRED release dates, VIX percentile, Treasury yields, real put/call, Finnhub news/earnings, AlphaVantage sentiment.",
        "integrated_as": "real_data(), /api/dow/real",
    },
    {
        "file": "econ_actual.py",
        "use": "Economic actual/forecast/previous, surprise scoring, ForexFactory critical events.",
        "integrated_as": "econ(), /api/dow/econ",
    },
    {
        "file": "macro_data.py + macro_extras.py",
        "use": "FRED macro block, macro score, yield curve, earnings calendar, killzone timer, DXY correlation, FOMC countdown.",
        "integrated_as": "macro(), extras(), /api/dow/macro and /api/dow/extras",
    },
    {
        "file": "signal_filter.py + backtest_results.json",
        "use": "Validated thresholds: US30 minimum=32, strong=40, best R=2.5; daily timeframe is the validated edge.",
        "integrated_as": "quality(), /api/dow/quality and backtest(), /api/dow/backtest",
    },
    {
        "file": "validated.py",
        "use": "Validated historical-signal engine separated from the heavier live agent.",
        "integrated_as": "validated(), /api/dow/validated",
    },
    {
        "file": "tradeplan.py",
        "use": "Full trade plan: entry, stop, TP levels, reasons, invalidation, watch levels, text/html export.",
        "integrated_as": "trade_plan(), /api/dow/tradeplan",
    },
    {
        "file": "agent.py",
        "use": "Full previous Dow decision engine combining SMC, MTF, intermarket, macro, orderflow, regime, volatility, sentiment.",
        "integrated_as": "agent(), /api/dow/agent (heavy, cached)",
    },
    {
        "file": "window.py",
        "use": "Trading-window quality based on spread/cost vs average volatility by hour.",
        "integrated_as": "window(), /api/dow/window",
    },
    {
        "file": "cross_asset.py",
        "use": "Gold ↔ Dow correlation and cross-asset position sizing.",
        "integrated_as": "cross_asset(), /api/dow/cross",
    },
    {
        "file": "live_feed.py",
        "use": "Yahoo quote polling / SSE design; useful reference for future live ticks.",
        "integrated_as": "source copied; not auto-started to keep FastAPI light",
    },
]


def extraction_manifest() -> Dict[str, Any]:
    return {
        "ok": True,
        "repo": "https://github.com/Tanha2419/dow-analyzer1.git",
        "asset": "US30 / Dow Jones",
        "modules_count": len(EXTRACTED_MODULES),
        "modules": EXTRACTED_MODULES,
        "copied_reference_dir": "dow_analyzer1_original/",
        "note_fa": "ماژول‌های کاربردی داوجونز از پروژه قبلی استخراج و به FastAPI/Render فعلی متصل شدند؛ Flask server قدیمی فقط به‌عنوان مرجع نگهداری شده است.",
    }


def reference_config() -> Dict[str, Any]:
    return {"ok": True, **refcfg.as_dict()}


def broker_profile() -> Dict[str, Any]:
    b = refcfg.BROKER_TRENDO
    ex = dict(b.get("account_example", {}))
    balance = float(ex.get("balance_usd", 10.0))
    leverage = float(ex.get("leverage", 50.0))
    min_lot = float(ex.get("min_lot", 0.01))
    price = float(ex.get("price_reference", 50844.0))
    per_point = float(refcfg.CONTRACT["US30"]["per_point"])
    notional = price * per_point * min_lot
    margin = notional / leverage
    shortage = max(0.0, margin - balance)
    return _clean({
        "ok": True,
        "broker": b,
        "computed": {
            "balance_usd": balance,
            "leverage": leverage,
            "min_lot": min_lot,
            "price_reference": price,
            "notional_usd": round(notional, 2),
            "required_margin_usd": round(margin, 2),
            "margin_shortage_usd": round(shortage, 2),
            "can_open_min_lot": shortage <= 0,
            "verdict_fa": "با موجودی فعلی ۰.۰۱ لات قابل باز شدن است." if shortage <= 0 else f"با {balance:.2f}$، حداقل ۰.۰۱ لات حدود {shortage:.2f}$ کسری مارجین دارد.",
        },
    })


def profile() -> Dict[str, Any]:
    return _safe("assets.profile", lambda: {
        "ok": True,
        "asset_profile": _m("assets").profile("US30"),
        "assets": _m("assets").list_assets(),
    })


def cash() -> Dict[str, Any]:
    return _cached("dow_cash", 20, lambda: _safe("dow_cash", lambda: {
        "ok": True,
        "cash_price": _m("dow_cash").cash_price(),
        "freshest": _m("dow_cash").freshest(),
        "basis": _m("dow_cash").compute_basis(),
    }))


def hours() -> Dict[str, Any]:
    return _safe("market_hours", lambda: {
        "ok": True,
        "status": _m("market_hours").market_status(),
        "killzones_tehran": _m("market_hours").killzones_tehran(),
        "upcoming_holidays": _m("market_hours").upcoming_holidays(8),
    })


def window() -> Dict[str, Any]:
    return _cached("window:US30", 180, lambda: _safe("window.status", lambda: _m("window").status("US30")))


def quality(score: Optional[float] = None, interval: str = "1d") -> Dict[str, Any]:
    sf = _m("signal_filter")
    if score is None:
        return _safe("signal_filter.evidence", lambda: sf.evidence("US30"))
    return _safe("signal_filter.assess", lambda: sf.assess("US30", float(score), interval))


def backtest() -> Dict[str, Any]:
    def _load():
        p = APP_DIR / "backtest_results.json"
        d = json.loads(p.read_text(encoding="utf-8"))
        runs = {k: v for k, v in (d.get("runs") or {}).items() if str(k).startswith("US30")}
        summary = []
        for k, v in runs.items():
            summary.append({
                "run": k,
                "n": v.get("n"),
                "win_rate": v.get("win_rate"),
                "avg_r": v.get("avg_r"),
                "expectancy": v.get("expectancy"),
                "strong": v.get("strong"),
                "by_grade": v.get("by_grade"),
                "by_direction": v.get("by_direction"),
                "beats_random": v.get("beats_random"),
            })
        return {"ok": True, "generated": d.get("generated"), "method": d.get("method"), "us30_runs": runs, "summary": summary}
    return _safe("backtest_results", _load)


def macro(with_earnings: bool = False) -> Dict[str, Any]:
    return _cached(f"macro:{int(with_earnings)}", 900, lambda: _safe("macro_data.build_macro", lambda: _m("macro_data").build_macro(with_earnings=with_earnings)))


def extras() -> Dict[str, Any]:
    return _cached("extras:US30", 60, lambda: _safe("macro_extras.build_extras", lambda: _m("macro_extras").build_extras("US30")))


def econ(what: str = "all") -> Dict[str, Any]:
    ea = _m("econ_actual")
    what = (what or "all").lower()
    def _build():
        if what == "surprise":
            return ea.surprise_score()
        if what == "critical":
            return ea.critical_events(72)
        if what == "ff":
            return ea.forexfactory("thisweek")
        out = ea.calendar_actuals()
        out["surprise_score"] = ea.surprise_score()
        out["critical"] = ea.critical_events(72)
        return out
    return _cached(f"econ:{what}", 900, lambda: _safe("econ_actual", _build))


def context(with_mtf: bool = False) -> Dict[str, Any]:
    return _cached(f"context:{int(with_mtf)}", 300, lambda: _safe("market_context.build_context", lambda: _m("market_context").build_context(asset="US30", with_mtf=with_mtf)))


def orderflow(interval: str = "1h") -> Dict[str, Any]:
    interval = interval if interval in {"5m", "15m", "30m", "1h", "1d"} else "1h"
    return _cached(f"orderflow:{interval}", 300, lambda: _safe("orderflow.build_orderflow", lambda: _m("orderflow").build_orderflow("DIA", interval, with_seasonality=True)))


def volatility() -> Dict[str, Any]:
    return _cached("volatility:DIA", 900, lambda: _safe("volatility.build_volatility", lambda: _m("volatility").build_volatility("DIA", asset="US30")))


def real_data(what: str = "all") -> Dict[str, Any]:
    rd = _m("real_data")
    what = (what or "all").lower()
    def _build():
        if what == "calendar":
            return rd.economic_calendar(30)
        if what == "treasury":
            return rd.treasury_yields()
        if what == "putcall":
            return rd.put_call_real("DIA")
        if what == "vix":
            # real_data.vix_percentile only needs the value; use yfinance local fallback.
            import yfinance as yf
            v = yf.Ticker("^VIX").history(period="5d")["Close"].dropna()
            return rd.vix_percentile(float(v.iloc[-1]))
        if what == "news":
            return rd.finnhub_news(limit=40)
        if what == "earnings":
            return rd.finnhub_earnings(45)
        return rd.build_real_data("DIA", asset="US30")
    return _cached(f"real:{what}", 900, lambda: _safe("real_data", _build))


def sentiment() -> Dict[str, Any]:
    return _cached("sentiment:US30", 900, lambda: _safe("sentiment_ext.build_sentiment_ext", lambda: _m("sentiment_ext").build_sentiment_ext("US30")))


def intelligence(interval: str = "1h", bars: int = 220, with_ml: bool = False) -> Dict[str, Any]:
    def _build():
        import market_data as md
        fr = md.fetch_ohlcv(interval=interval, bars=max(bars, 220))
        return _m("regime_ai").run_intelligence(fr.df.tail(max(bars, 220)), with_ml=with_ml)
    return _cached(f"intel:{interval}:{int(with_ml)}", 300, lambda: _safe("regime_ai.run_intelligence", _build))


def validated(interval: str = "1d") -> Dict[str, Any]:
    interval = interval if interval in {"5m", "15m", "30m", "1h", "1d"} else "1d"
    return _cached(f"validated:{interval}", 300, lambda: _safe("validated.cached", lambda: _m("validated").cached(asset="US30", interval=interval)))


def trade_plan(interval: str = "1h", equity: float = 10000, risk: float = 1.0, multi: bool = False) -> Dict[str, Any]:
    interval = interval if interval in {"5m", "15m", "30m", "1h", "1d"} else "1h"
    tp = _m("tradeplan")
    def _build():
        if multi:
            return tp.build_multi("US30", ["1h", "1d"], equity, risk)
        return tp.build_plan("US30", interval, equity, risk)
    return _cached(f"plan:{interval}:{equity}:{risk}:{int(multi)}", 600, lambda: _safe("tradeplan", _build))


def cross_asset() -> Dict[str, Any]:
    return _cached("cross_asset", 1800, lambda: _safe("cross_asset.build", lambda: _m("cross_asset").build()))


def agent(interval: str = "1h", equity: float = 10000, with_ml: bool = False, with_mtf: bool = False) -> Dict[str, Any]:
    interval = interval if interval in {"5m", "15m", "30m", "1h", "1d"} else "1h"
    def _build():
        out = _m("agent").decide(interval=interval, equity=equity, with_ml=with_ml, with_mtf=with_mtf, with_coalition=True, scale=True, asset="US30")
        # intelligence can be very large; keep endpoint usable.
        if not with_ml:
            out.pop("intelligence", None)
        return out
    return _cached(f"agent:{interval}:{equity}:{int(with_ml)}:{int(with_mtf)}", 600, lambda: _safe("agent.decide", _build))


def suite(light: bool = True, interval: str = "1h") -> Dict[str, Any]:
    """Aggregate useful dow-analyzer1 resources.

    light=True avoids the very heavy old full agent/tradeplan computations and is
    suitable for dashboard startup. Heavy endpoints stay available separately.
    """
    out = {
        "ok": True,
        "manifest": extraction_manifest(),
        "reference": reference_config(),
        "broker": broker_profile(),
        "profile": profile(),
        "hours": hours(),
        "window": window(),
        "quality_evidence": quality(),
        "backtest": backtest(),
        "cash": cash(),
        "extras": extras(),
        "context": context(with_mtf=False),
        "sentiment": sentiment(),
    }
    if not light:
        out.update({
            "macro": macro(with_earnings=False),
            "econ": econ("critical"),
            "orderflow": orderflow(interval),
            "volatility": volatility(),
            "real": real_data("treasury"),
            "intelligence": intelligence(interval, with_ml=False),
            "validated": validated("1d"),
        })
    return _clean(out)
