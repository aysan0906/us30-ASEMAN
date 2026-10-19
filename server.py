from __future__ import annotations
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
server.py — Render-ready FastAPI server for the dedicated US30 dashboard.

Pattern follows ASEMAN crypto source:
- single FastAPI app
- root serves index.html
- /api/* endpoints for ticker, analysis, plan, provider status
- /healthz for Render/UptimeRobot
"""


import os
import sys
from contextlib import asynccontextmanager
import subprocess

import fastapi
import uvicorn

import dow_cash as dcash
from pathlib import Path
from typing import Optional, List, Dict, Any
from pydantic import BaseModel
import json, time, threading, urllib.request, urllib.parse, socket
# Enforce global socket timeout to prevent any upstream API lag from locking the server
socket.setdefaulttimeout(4.0)
from datetime import datetime, timedelta, timezone

from fastapi import Depends, FastAPI, HTTPException, Query, Request

from us30_supreme_arbiter import us30_supreme_arbiter
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

import market_data as md
import us30_engine as engine
import aseman_resources as aseman
import dow_analyzer_resources as dowres
import execution_guard as execguard
import snapshot as snap

APP_DIR = Path(__file__).resolve().parent


def _valid_us30_quote(interval: str = "1h") -> Dict[str, Any]:
    """Return a fresh executable quote only; display proxies are not trade quotes."""
    try:
        import trendo_engine
        quote = trendo_engine.get_trendo_us30_live()
        if isinstance(quote, dict) and quote.get("ok") and quote.get("tradable") is True and not quote.get("is_synthetic"):
            bid = float(quote.get("bid"))
            ask = float(quote.get("ask"))
            age = float(quote.get("age_seconds", 0.0) or 0.0)
            if bid > 10000 and ask >= bid and age <= 3.0:
                return {"ok": True, "quote": quote, "price": bid, "tradable": True}
    except Exception:
        pass
    try:
        quote = engine.ticker(interval)
        price = quote.get("price") if isinstance(quote, dict) else None
        price = float(price) if price is not None else None
        age = float(quote.get("age_seconds", 0.0) or 0.0) if isinstance(quote, dict) else 999.0
        if quote.get("ok") and quote.get("tradable") is True and price is not None and price > 10000 and age <= 3.0:
            return {"ok": True, "quote": quote, "price": price, "tradable": True}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    return {
        "ok": False,
        "error": "EXECUTABLE_US30_QUOTE_UNAVAILABLE",
        "message": "قیمت اجرایی تازه از Trendo/CFD در دسترس نیست؛ قیمت DIA یا شاخص نقدی جایگزین quote بروکر نمی‌شود.",
    }


def _unavailable_module(module: str, reason: str) -> Dict[str, Any]:
    return {"ok": False, "module": module, "error": "LIVE_DATA_UNAVAILABLE", "message": reason}


def _analysis_is_real_index(data: Dict[str, Any]) -> bool:
    meta = data.get("meta") if isinstance(data, dict) else {}
    if not isinstance(meta, dict):
        return False
    symbol = str(meta.get("symbol", "")).upper()
    # Only an actual US30/US30USD feed is executable. ^DJI, YM=F and DIA are references/proxies.
    return "US30" in symbol and "DIA" not in symbol


def _block_proxy_trade(data: Dict[str, Any]) -> Dict[str, Any]:
    """Preserve research output but prevent proxy candles from becoming executable plans."""
    if not _analysis_is_real_index(data):
        meta = data.setdefault("meta", {})
        if isinstance(meta, dict):
            meta["tradable"] = False
            meta["data_quality"] = "PROXY_NOT_EXECUTABLE"
            meta["execution_note"] = "دادهٔ کندلی از نماد اجرایی واقعی US30 نیست؛ تحلیل فقط پژوهشی است."
        sig = data.get("signal")
        if isinstance(sig, dict):
            sig["direction"] = 0
            sig["label"] = "WAIT — PROXY DATA"
            sig["grade"] = "—"
            sig["plan"] = {}
            sig["verdict_fa"] = "منبع کندل نماد اجرایی US30 نیست؛ هیچ معامله‌ای صادر نشود."
        data["position_sizing"] = {"ok": False, "note": "سایزینگ اجرایی با دادهٔ proxy ممنوع است."}
        data["source_valid"] = False
        data["tradable"] = False
    else:
        meta = data.setdefault("meta", {})
        if isinstance(meta, dict):
            meta["source_valid"] = True
            meta["data_quality"] = "US30_INDEX_OHLCV"
            meta["tradable"] = False
        data["source_valid"] = True
        # A valid data source alone is not execution approval.
        data["tradable"] = False
    return data


def verify_admin_auth(request: Request):
    """Fail-closed authentication for administrative endpoints."""
    admin_key = os.environ.get("ADMIN_SECRET_KEY", "").strip()
    if not admin_key:
        raise HTTPException(
            status_code=503,
            detail="ADMIN_SECRET_KEY تنظیم نشده؛ عملیات مدیریتی غیرفعال است.",
        )
    auth_header = request.headers.get("X-Admin-Key", "")
    if not auth_header or not __import__("hmac").compare_digest(auth_header, admin_key):
        raise HTTPException(status_code=403, detail="دسترسی غیرمجاز: کلید مدیر اشتباه است.")
    return True

@asynccontextmanager
async def app_lifespan(app):
    """Start background workers after ASGI startup, never as a module import side effect."""
    if os.environ.get("DISABLE_BACKGROUND_WORKERS", "0").strip() != "1" and not getattr(app.state, "background_workers_started", False):
        app.state.background_workers_started = True
        threading.Thread(target=prewarm_signals_in_background, daemon=True, name="us30-prewarm").start()
        threading.Thread(target=us30_sentinel_auto_loop, daemon=True, name="us30-sentinel").start()
        threading.Thread(target=us30_telegram_interactive_poller, daemon=True, name="us30-telegram-poller").start()
    yield


app = FastAPI(
    title="US30 ASEMAN Smart Money Dashboard",
    description="Dedicated Dow Jones / US30 dashboard using ASEMAN architecture and the previous Dow Smart Money engine.",
    version="1.1.0",
    lifespan=app_lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://us30-aseman-1.onrender.com", "https://us30-aseman.onrender.com", "http://localhost:8000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(GZipMiddleware, minimum_size=500)


@app.middleware("http")
async def headers(request: Request, call_next):
    # 1. Enforce HTTPS redirect behind Render / Cloudflare reverse proxies
    proto = request.headers.get("x-forwarded-proto", "").lower()
    if proto == "http":
        https_url = request.url.replace(scheme="https")
        return RedirectResponse(url=str(https_url), status_code=301)

    response = await call_next(request)

    # 2. Enterprise HSTS (Forces HTTPS for 2 years)
    response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains; preload"

    # 3. Prevent MIME Sniffing & XSS Exploits
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

    # 4. Restrict dangerous hardware browser permissions
    response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=(), payment=()"

    # 5. Enterprise Content-Security-Policy with iframe preview permission
    response.headers["Content-Security-Policy"] = (
        "frame-ancestors 'self' https://*.onrender.com; "
        "default-src 'self' 'unsafe-inline' 'unsafe-eval' https: data: blob:; "
        "img-src 'self' https: data: blob:; "
        "script-src 'self' 'unsafe-inline' 'unsafe-eval' https: https://s3.tradingview.com; "
        "style-src 'self' 'unsafe-inline' https: https://fonts.googleapis.com; "
        "font-src 'self' https: data: https://fonts.gstatic.com; "
        "connect-src 'self' https: wss:; "
        "frame-src 'self' https: https://s.tradingview.com https://www.tradingview.com;"
    )

    response.headers["Cache-Control"] = "no-store"
    if "X-Frame-Options" in response.headers:
        del response.headers["X-Frame-Options"]
    return response


@app.api_route("/healthz", methods=["GET", "HEAD"])
@app.api_route("/health", methods=["GET", "HEAD"])
@app.api_route("/api/health", methods=["GET", "HEAD"])
@app.api_route("/ping", methods=["GET", "HEAD"])
def health_check():
    return {"status": "ok", "asset": "US30", "message": "healthy"}


@app.get("/api/status")
def status():
    return {
        "ok": True,
        "status": "online",
        "asset": "US30",
        "service": "US30 ASEMAN Smart Money Dashboard",
        "provider": md.provider_status(),
        "market": engine.market_state(),
    }


@app.get("/api/providers")
def providers():
    return {"ok": True, "data": md.provider_status()}


@app.get("/api/market-hours")
def market_hours():
    return engine.market_state()


_ticker_cache = {}

@app.get("/api/ticker")
def ticker(interval: str = Query("1h", description="5m, 15m, 30m, 1h, 1d")):
    try:
        now_ts = time.time()
        cached = _ticker_cache.get(interval)
        if cached and (now_ts - cached["time"] < 0.5):
            return cached["data"]
        data = engine.ticker(interval)
        if isinstance(data, dict) and data.get("ok") and isinstance(data.get("price"), (int, float)) and data["price"] > 10000:
            _ticker_cache[interval] = {"time": now_ts, "data": data}
        return data
    except Exception as e:
        cached = _ticker_cache.get(interval)
        if cached:
            return cached["data"]
        return JSONResponse(status_code=502, content={"ok": False, "error": str(e)})


@app.get("/api/candles")
def candles(
    interval: str = Query("1h", description="1m, 5m, 15m, 30m, 1h, 4h, 1d"),
    bars: int = Query(180, ge=80, le=600),
):
    if interval not in md.VALID_INTERVALS:
        return JSONResponse(status_code=422, content={"ok": False, "error": "INVALID_INTERVAL", "allowed": list(md.VALID_INTERVALS)})
    try:
        return engine.candles(interval, bars)
    except Exception as e:
        return JSONResponse(status_code=502, content={"ok": False, "error": str(e)})


_analysis_cache: Dict[str, Any] = {}

@app.get("/api/analyze")
@app.get("/api/analysis")
@app.get("/api/agent")
def analyze(
    interval: str = Query("1h", description="5m, 15m, 30m, 1h, 1d"),
    bars: int = Query(180, ge=80, le=600),
    fresh: bool = Query(False, description="Bypass short in-memory cache"),
    coalition: Optional[bool] = Query(None, description="Enable heavy bank-coalition layer"),
    equity: float = Query(10000, gt=0, description="For educational position sizing"),
    risk_pct: float = Query(1.0, gt=0, le=10, description="Risk percent for educational position sizing"),
    include_aseman: bool = Query(True, description="Attach ASEMAN extracted institutional suite"),
    include_dow: bool = Query(True, description="Attach dow-analyzer1 extracted resource suite"),
    guard_balance: float = Query(10.0, gt=0, description="Broker guard balance, default from user reference"),
    guard_leverage: float = Query(50.0, gt=0, description="Broker guard leverage"),
    guard_lot: float = Query(0.01, gt=0, description="Broker guard lot size"),
):
    if interval not in md.VALID_INTERVALS:
        return JSONResponse(status_code=422, content={"ok": False, "error": "INVALID_INTERVAL", "allowed": list(md.VALID_INTERVALS)})
    now = time.time()
    fresh_bool = bool(getattr(fresh, "default", fresh))
    cache_key = f"{interval}:{bars}:{coalition!r}:{int(bool(include_aseman))}:{int(bool(include_dow))}:{equity}:{risk_pct}:{guard_balance}:{guard_leverage}:{guard_lot}"
    if not fresh and cache_key in _analysis_cache and (now - _analysis_cache[cache_key]["time"] < 60.0):
        return _analysis_cache[cache_key]["data"]

    try:
        data = engine.build_analysis(
            interval=interval,
            bars=bars,
            force=fresh_bool,
            with_coalition=coalition,
            equity=equity,
            risk_pct=risk_pct,
        )
        data = _block_proxy_trade(data)
        if include_aseman:
            if not data.get("source_valid"):
                data["aseman_suite"] = {"ok": False, "tradable": False, "error": "PROXY_DATA_BLOCKED"}
            else:
                try:
                    data["aseman_suite"] = aseman.build_aseman_suite(data)
                except Exception as pack_error:
                    data["aseman_suite"] = {"success": False, "error": str(pack_error)}
        if include_dow:
            if not data.get("source_valid"):
                data["dow_suite"] = {"ok": False, "tradable": False, "error": "PROXY_DATA_BLOCKED"}
            else:
                try:
                    data["dow_suite"] = dowres.suite(light=True, interval=interval)
                except Exception as dow_error:
                    data["dow_suite"] = {"ok": False, "error": str(dow_error)}
        if not data.get("source_valid"):
            data["execution_guard"] = {"ok": False, "trade_allowed": False, "status": "PROXY_DATA_BLOCKED"}
        else:
            try:
                data["execution_guard"] = execguard.evaluate(data, interval=interval, balance=guard_balance, leverage=guard_leverage, lot=guard_lot)
            except Exception as guard_error:
                data["execution_guard"] = {"ok": False, "trade_allowed": False, "error": str(guard_error)}
            data["tradable"] = bool(data["execution_guard"].get("trade_allowed") is True)
        _analysis_cache[cache_key] = {"time": now, "data": data}
        return data
    except Exception as e:
        return JSONResponse(status_code=502, content={
            "ok": False,
            "tradable": False,
            "error": "ANALYSIS_UNAVAILABLE",
            "message": "تحلیل معتبر ساخته نشد؛ دادهٔ جایگزین/سیگنال ساختگی برگردانده نمی‌شود.",
            "detail": str(e)[:300],
        })


def get_analysis_360_data(interval: str = "15m", price: Optional[float] = None) -> Dict[str, Any]:
    interval = interval if interval in md.VALID_INTERVALS else "15m"
    try:
        data = engine.build_analysis(interval=interval, bars=180, force=False)
    except Exception as exc:
        return {"ok": False, "tradable": False, "error": "ANALYSIS360_UNAVAILABLE", "message": str(exc)}
    if not isinstance(data, dict) or not data.get("ok"):
        return {"ok": False, "tradable": False, "error": "ANALYSIS360_UNAVAILABLE"}
    data = _block_proxy_trade(data)
    return {
        "ok": True,
        "tradable": False,
        "source_valid": bool(data.get("source_valid")),
        "price": (data.get("price") or {}).get("last"),
        "interval": interval,
        "source": (data.get("meta") or {}).get("symbol"),
        "source_note": (data.get("meta") or {}).get("execution_note") or (data.get("meta") or {}).get("source_note"),
        "structure": data.get("structure", {}),
        "liquidity": data.get("liquidity", {}),
        "fvgs": data.get("fvgs", []),
        "order_blocks": data.get("order_blocks", []),
        "signal": data.get("signal", {}),
        "timestamp": (data.get("meta") or {}).get("generated"),
    }


@app.get("/api/analysis360")
def get_analysis_360_endpoint(interval: str = Query("15m")):
    if interval not in md.VALID_INTERVALS:
        return JSONResponse(status_code=422, content={"ok": False, "error": "INVALID_INTERVAL", "allowed": list(md.VALID_INTERVALS)})
    return get_analysis_360_data(interval)


@app.get("/api/plan")
def plan(
    interval: str = Query("1h"),
    bars: int = Query(180, ge=80, le=600),
    fresh: bool = Query(False),
    equity: float = Query(10000, gt=0),
    risk_pct: float = Query(1.0, gt=0, le=10),
):
    if interval not in md.VALID_INTERVALS:
        return JSONResponse(status_code=422, content={"ok": False, "error": "INVALID_INTERVAL", "allowed": list(md.VALID_INTERVALS)})
    try:
        data = engine.build_analysis(interval=interval, bars=bars, force=fresh, equity=equity, risk_pct=risk_pct)
        data = _block_proxy_trade(data)
        guard_result = execguard.evaluate(data, interval=interval, balance=equity, leverage=50.0, lot=0.01) if data.get("source_valid") else {"ok": False, "trade_allowed": False, "status": "PROXY_DATA_BLOCKED"}
        data["execution_guard"] = guard_result
        data["tradable"] = bool(guard_result.get("trade_allowed") is True)
        return {
            "ok": True,
            "tradable": bool(data.get("tradable")),
            "execution_guard": guard_result,
            "asset": "US30",
            "meta": data.get("meta"),
            "price": data.get("price"),
            "signal": data.get("signal"),
            "position_sizing": data.get("position_sizing"),
            "market": data.get("market"),
        }
    except Exception as e:
        return JSONResponse(status_code=502, content={"ok": False, "error": str(e)})


@app.get("/api/aseman/macro")
def aseman_macro():
    return aseman.AsemanMacroShieldUS30.get_macro_shield_status()


@app.get("/api/aseman/news")
def aseman_news():
    return aseman.AsemanNewsCircuitBreakerUS30.fetch_live_news()


@app.get("/api/aseman/options")
def aseman_options(symbol: str = Query("DIA", description="DIA or SPY recommended")):
    return aseman.AsemanOptionsUS30.get_options_analytics(symbol)


@app.get("/api/aseman/alpha")
def aseman_alpha():
    return aseman.AsemanAlphaMatrixUS30.get_matrix()



@app.get("/api/us30/unified-signals")
def get_us30_unified_signals_api():
    try:
        import us30_unified_signals as uus
        p_curr = None
        try:
            cash_info = dcash.freshest()
            candidate = (cash_info.get("best") or {}).get("index") if isinstance(cash_info, dict) else None
            candidate = float(candidate) if candidate is not None else None
            if candidate is not None and candidate > 10000:
                p_curr = candidate
        except Exception:
            p_curr = None
        data = uus.get_us30_unified_signals(p_curr)
        return {"ok": bool(data.get("ok")), "data": data, "tradable": bool(data.get("tradable", False))}
    except Exception as e:
        return {"ok": False, "error": str(e)}

@app.get("/api/aseman/journal")
def aseman_journal():
    return aseman.AsemanMacroJournalUS30.get_journal()


@app.get("/api/aseman/kelly")
def aseman_kelly(
    balance: float = Query(10000, gt=0),
    risk_pct: float = Query(1.0, gt=0, le=20),
    entry: float = Query(50000, gt=0),
    stop: float = Query(49500, gt=0),
    tp: float = Query(51000, gt=0),
    win_rate: float = Query(55, ge=5, le=95),
    direction: str = Query("LONG"),
):
    return aseman.AsemanKellyRiskUS30.calculate(balance, risk_pct, entry, stop, tp, win_rate, direction)


@app.get("/api/aseman/golden")
def aseman_golden(
    interval: str = Query("1h"),
    bars: int = Query(180, ge=80, le=600),
    direction: str = Query("AUTO", description="AUTO, LONG, SHORT"),
):
    if interval not in md.VALID_INTERVALS:
        return JSONResponse(status_code=422, content={"ok": False, "error": "INVALID_INTERVAL", "allowed": list(md.VALID_INTERVALS)})
    data = engine.build_analysis(interval=interval, bars=bars, force=False)
    if not _analysis_is_real_index(data):
        return {"ok": False, "trade_allowed": False, "status": "PROXY_DATA_BLOCKED", "message": "کندل‌های نماد اجرایی US30 در دسترس نیستند."}
    d = direction.upper()
    if d == "AUTO":
        sig = data.get("signal", {})
        raw_dir = int(sig.get("direction", 0) or 0)
    if raw_dir > 0:
        d = "LONG"
    elif raw_dir < 0:
        d = "SHORT"
    else:
        d = "NEUTRAL" # 0 strictly means NEUTRAL / WAIT, NEVER LONG!
    return aseman.AsemanGoldenFiltersUS30.evaluate(data, d)


@app.get("/api/aseman/suite")
def aseman_suite(
    interval: str = Query("1h"),
    bars: int = Query(180, ge=80, le=600),
    fresh: bool = Query(False),
    equity: float = Query(10000, gt=0),
    risk_pct: float = Query(1.0, gt=0, le=10),
):
    if interval not in md.VALID_INTERVALS:
        return JSONResponse(status_code=422, content={"ok": False, "error": "INVALID_INTERVAL", "allowed": list(md.VALID_INTERVALS)})
    data = engine.build_analysis(interval=interval, bars=bars, force=fresh, equity=equity, risk_pct=risk_pct)
    if not _analysis_is_real_index(data):
        return {"ok": False, "tradable": False, "error": "PROXY_DATA_BLOCKED", "message": "تحلیل نهادی اجرایی با کندل‌های proxy تولید نمی‌شود."}
    return aseman.build_aseman_suite(data)


@app.get("/api/dow/manifest")
def dow_manifest():
    return dowres.extraction_manifest()


@app.get("/api/dow/profile")
def dow_profile():
    return dowres.profile()


@app.get("/api/dow/reference")
def dow_reference():
    return dowres.reference_config()


@app.get("/api/dow/broker")
def dow_broker():
    return dowres.broker_profile()


@app.get("/api/dow/data-health")
def dow_data_health():
    try:
        return {"ok": True, "compare": dcash.compare(), "basis": dcash.compute_basis(), "freshest": dcash.freshest()}
    except Exception as e:
        return JSONResponse(status_code=502, content={"ok": False, "error": str(e)})


@app.get("/api/snapshot")
def snapshot_status():
    """Snapshot status for Render/GitHub Actions precomputed cache."""
    return snap.status()


@app.post("/api/snapshot")
async def snapshot_push(request: Request):
    """Securely receive precomputed items from GitHub Actions.

    Header key: X-Snapshot-Key
    Body: {"items": {"agent:US30:1d": {...}}, "built_at": 123}
    """
    if not snap.enabled():
        return JSONResponse(status_code=503, content={"ok": False, "error": "SNAPSHOT_KEY تنظیم نشده"})
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > 1_000_000:
                return JSONResponse(status_code=413, content={"ok": False, "error": "SNAPSHOT_PAYLOAD_TOO_LARGE"})
        except ValueError:
            return JSONResponse(status_code=400, content={"ok": False, "error": "INVALID_CONTENT_LENGTH"})
    given = request.headers.get("X-Snapshot-Key", "")
    if not snap.check_key(given):
        return JSONResponse(status_code=403, content={"ok": False, "error": "کلید نامعتبر"})
    try:
        raw_body = await request.body()
        if len(raw_body) > 1_000_000:
            return JSONResponse(status_code=413, content={"ok": False, "error": "SNAPSHOT_PAYLOAD_TOO_LARGE"})
        body = json.loads(raw_body.decode("utf-8"))
    except Exception:
        return JSONResponse(status_code=400, content={"ok": False, "error": "INVALID_JSON"})
    items = body.get("items") if isinstance(body, dict) else None
    if not isinstance(items, dict) or not items:
        return JSONResponse(status_code=400, content={"ok": False, "error": "items خالی است"})
    if len(items) > 100:
        return JSONResponse(status_code=413, content={"ok": False, "error": "TOO_MANY_SNAPSHOT_ITEMS", "max_items": 100})
    saved = []
    for k, v in items.items():
        if isinstance(k, str) and 1 <= len(k) <= 120:
            snap.save(k, v, built_at=body.get("built_at"))
            saved.append(k)
    return {"ok": True, "saved": saved, "count": len(saved)}


_guard_cache: Dict[str, Any] = {}

@app.get("/api/dow/guard")
def dow_guard(
    interval: str = Query("1h"),
    bars: int = Query(120, ge=80, le=600),
    fresh: bool = Query(False),
    balance: float = Query(10.0, gt=0),
    leverage: float = Query(50.0, gt=0),
    lot: float = Query(0.01, gt=0),
):
    global _guard_cache
    if interval not in md.VALID_INTERVALS:
        return JSONResponse(status_code=422, content={"ok": False, "trade_allowed": False, "error": "INVALID_INTERVAL", "allowed": list(md.VALID_INTERVALS)})
    now = time.time()
    # Cache key includes all query parameters
    cache_key = f"{interval}_{bars}_{balance}_{leverage}_{lot}"
    if isinstance(_guard_cache, dict) and not fresh:
        cached = _guard_cache.get(cache_key)
        if cached and (now - cached.get("time", 0.0) < 20.0):
            return cached["data"]

    # Use REAL analysis rather than dummy 75 score / 135 atr
    analysis = engine.build_analysis(interval=interval, bars=bars, force=fresh)
    if not analysis or not analysis.get("ok") or not _analysis_is_real_index(analysis):
        return {
            "ok": False,
            "trade_allowed": False,
            "status": "FAIL_CLOSED_NO_EXECUTABLE_INDEX_DATA",
            "reason": "عدم دسترسی به داده‌های زنده و تحلیل بازار جهت ارزیابی ریسک",
            "timestamp": now
        }
    res = execguard.evaluate(analysis, interval=interval, balance=balance, leverage=leverage, lot=lot)
    if not isinstance(_guard_cache, dict):
        _guard_cache = {}
    _guard_cache[cache_key] = {"time": now, "data": res}
    return res


@app.get("/api/dow/cash")
def dow_cash_endpoint():
    return dowres.cash()



def generate_us30_intelligent_answer(question: str, interval: str = "1h") -> str:
    try:
        from dow_advisor_engine import DowAIAdvisor
        return DowAIAdvisor.answer_question(question, interval)
    except Exception as e:
        return "قیمت و تحلیل معتبر داوجونز در دسترس نیست؛ هیچ جهت معاملاتی پیشنهاد نمی‌شود."

@app.api_route("/api/chat", methods=["GET", "POST"])
@app.api_route("/api/advisor/chat", methods=["GET", "POST"])
@app.api_route("/api/dow/chat", methods=["GET", "POST"])
async def universal_chat_endpoint(request: Request, q: str = Query(""), interval: str = Query("1h")):
    try:
        question = q
        if request.method == "POST":
            try:
                body = await request.json()
                if isinstance(body, dict):
                    question = body.get("q") or body.get("question") or body.get("message") or question
                    interval = body.get("interval") or interval
            except Exception:
                pass
        
        if not question:
            question = "وضعیت داوجونز چطوره؟"
            
        answer_text = generate_us30_intelligent_answer(question, interval)
        return {
            "ok": True,
            "answer": answer_text,
            "reply": answer_text,
            "response": answer_text,
            "confident": True,
            "topic": "us30_smart_money",
            "timeframe": interval
        }
    except Exception as e:
        err_msg = "تحلیل داوجونز در دسترس نیست؛ دادهٔ جایگزین یا جهت معاملاتی ساختگی ارائه نمی‌شود."
        return {"ok": False, "confident": False, "answer": err_msg, "reply": err_msg, "response": err_msg}

_coalition_cache: Dict[str, Any] = {}

@app.get("/api/dow/coalition")
def dow_coalition_endpoint():
    return _unavailable_module("coalition", "اجماع بانک‌ها از قیمت‌ها/داده‌های واقعی اعضا باید محاسبه شود؛ اعضای ثابت و اعداد نمونه دیگر به‌عنوان زنده ارائه نمی‌شوند.")

@app.get("/api/dow/institutional-layers")
def dow_institutional_layers(interval: str = Query("1h")):
    return _unavailable_module("institutional_layers", "لایه‌های orderflow و اجماع نهادی تا اتصال فیدهای واقعی غیرفعال‌اند.")

@app.get("/api/dow/hours")
def dow_hours():
    return dowres.hours()


@app.get("/api/dow/window")
def dow_window():
    return dowres.window()


@app.get("/api/dow/quality")
def dow_quality(
    score: Optional[float] = Query(None),
    interval: str = Query("1d"),
):
    return dowres.quality(score, interval)


@app.get("/api/dow/backtest")
def dow_backtest():
    return dowres.backtest()


@app.get("/api/dow/macro")
def dow_macro(with_earnings: bool = Query(False)):
    return dowres.macro(with_earnings)


@app.get("/api/dow/extras")
def dow_extras():
    return dowres.extras()


@app.get("/api/dow/econ")
def dow_econ(what: str = Query("all", description="all, surprise, critical, ff")):
    return dowres.econ(what)


@app.get("/api/dow/context")
def dow_context(with_mtf: bool = Query(False)):
    return dowres.context(with_mtf)


@app.get("/api/dow/orderflow")
def dow_orderflow(interval: str = Query("1h")):
    return _unavailable_module("orderflow", "OHLCV از DIA یا شاخص عمومی orderflow واقعی/Level 2 را نشان نمی‌دهد؛ CVD و بلوک‌ترید ساختگی ارائه نمی‌شوند.")

@app.get("/api/dow/volatility")
def dow_volatility():
    return dowres.volatility()


@app.get("/api/dow/real")
def dow_real(what: str = Query("all", description="all, calendar, treasury, putcall, vix, news, earnings")):
    return dowres.real_data(what)


@app.get("/api/dow/sentiment")
def dow_sentiment():
    return dowres.sentiment()


@app.get("/api/dow/intelligence")
def dow_intelligence(
    interval: str = Query("1h"),
    bars: int = Query(220, ge=120, le=700),
    with_ml: bool = Query(False),
):
    return dowres.intelligence(interval, bars, with_ml)


@app.get("/api/dow/validated")
def dow_validated(interval: str = Query("1d")):
    return dowres.validated(interval)


@app.get("/api/dow/tradeplan")
def dow_tradeplan(
    interval: str = Query("1h"),
    equity: float = Query(10000, gt=0),
    risk: float = Query(1.0, gt=0, le=20),
    multi: bool = Query(False),
):
    if "US30" not in md.selected_symbol().upper() or "DIA" in md.selected_symbol().upper():
        return _unavailable_module("tradeplan", "DATA_SYMBOL فعلی نماد اجرایی US30 نیست؛ پلن معاملاتی غیرفعال است.")
    if interval in getattr(execguard, "BAD_INTERVALS", set()):
        return _unavailable_module("tradeplan", "این تایم‌فریم هنوز برای سیگنال مستقل تأیید نشده است.")
    return dowres.trade_plan(interval, equity, risk, multi)

@app.get("/api/dow/cross")
def dow_cross():
    return dowres.cross_asset()


@app.get("/api/dow/agent")
def dow_agent(
    interval: str = Query("1h"),
    equity: float = Query(10000, gt=0),
    with_ml: bool = Query(False),
    with_mtf: bool = Query(False),
):
    if "US30" not in md.selected_symbol().upper() or "DIA" in md.selected_symbol().upper():
        return _unavailable_module("agent", "DATA_SYMBOL فعلی نماد اجرایی US30 نیست؛ عامل سیگنال خروجی معاملاتی نمی‌دهد.")
    if interval in getattr(execguard, "BAD_INTERVALS", set()):
        return _unavailable_module("agent", "این تایم‌فریم هنوز برای سیگنال مستقل تأیید نشده است.")
    return dowres.agent(interval, equity, with_ml, with_mtf)

@app.get("/api/dow/suite")
def dow_suite(
    light: bool = Query(True),
    interval: str = Query("1h"),
):
    return dowres.suite(light, interval)



# ============================================================================
# TELEGRAM DISPATCHER & SENTINEL AUTO-PILOT (ASEMAN ARCHITECTURE FOR US30)
# ============================================================================
TG_CONFIG_FILE = APP_DIR / "telegram_config.json"
_us30_sentinel_stats = {
    "is_running": False,
    "last_check_utc": None,
    "last_check_tehran": None,
    "signals_sent_total": 0,
    "last_signal_time": None,
    "last_error": None
}

_us30_interactive_bot_stats = {
    "is_running": False,
    "last_poll_utc": None,
    "last_update_id": 0,
    "queries_answered_total": 0,
    "last_query": None,
    "last_response": None,
    "last_error": None
}

class DowAdvisorQuestionRequest(BaseModel):
    question: str
    price: Optional[float] = None

class US30TelegramConfigRequest(BaseModel):
    bot_token: Optional[str] = ""
    chat_id: Optional[str] = ""
    auto_pilot: Optional[bool] = False
    interval_minutes: Optional[int] = 15
    min_score: Optional[int] = 70

class US30TelegramSendRequest(BaseModel):
    bot_token: Optional[str] = None
    chat_id: Optional[str] = None
    interval: Optional[str] = "15m"
    signal_type: Optional[str] = "scalp"  # "scalp", "swing", or "both"

def get_dispatched_journal_stats() -> Dict[str, Any]:
    recs = []
    if DISPATCHED_SIGNALS_FILE.exists():
        with open(DISPATCHED_SIGNALS_FILE, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    try:
                        recs.append(json.loads(line))
                    except Exception:
                        pass
    total = len(recs)
    wins = [r for r in recs if r.get("status") == "WIN"]
    losses = [r for r in recs if r.get("status") == "LOSS"]

    total_tp = sum(r.get("pnl_pts", 0) for r in wins)
    total_sl = abs(sum(r.get("pnl_pts", 0) for r in losses))
    net_pts = total_tp - total_sl
    win_rate = round((len(wins) / total) * 100, 1) if total > 0 else 0.0

    return {
        "total_signals": total,
        "total_tp_pts": total_tp,
        "total_sl_pts": total_sl,
        "net_pts": net_pts,
        "win_rate": win_rate,
        "wins_count": len(wins),
        "losses_count": len(losses)
    }

def is_us30_market_in_active_session() -> tuple[bool, str, Dict[str, Any]]:
    """
    Checks if the US30 market is within the allowed institutional trading window:
    1. Weekdays only: Monday to Friday (Saturday & Sunday 100% closed).
    2. Session Window: From London Open (07:00 UTC / 10:30 Iran) to New York Close (21:00 UTC / 00:30 Iran).
    """
    now_utc = datetime.now(timezone.utc)
    weekday = now_utc.weekday()  # 0=Monday, 4=Friday, 5=Saturday, 6=Sunday
    hour_utc = now_utc.hour
    minute_utc = now_utc.minute
    time_val_utc = hour_utc + (minute_utc / 60.0)

    # 1. Weekend Check (Saturday & Sunday)
    if weekday == 5:  # Saturday
        return False, "بازار داوجونز در روز شنبه تعطیل است (تعطیلات آخر هفته وال‌استریت)", {
            "is_open": False,
            "phase": "WEEKEND_SATURDAY",
            "label": "تعطیلات آخر هفته وال‌استریت (شنبه)",
            "countdown": "بازگشایی سشن لندن: دوشنبه ساعت ۱۰:۳۰ صبح به وقت ایران"
        }
    elif weekday == 6:  # Sunday
        return False, "بازار داوجونز در روز یکشنبه تعطیل است (تعطیلات آخر هفته وال‌استریت)", {
            "is_open": False,
            "phase": "WEEKEND_SUNDAY",
            "label": "تعطیلات آخر هفته وال‌استریت (یکشنبه)",
            "countdown": "بازگشایی سشن لندن: فردا دوشنبه ساعت ۱۰:۳۰ صبح به وقت ایران"
        }

    # 2. Weekday Hours Check (Monday to Friday: 07:00 UTC to 21:00 UTC)
    # London Open: 07:00 UTC (10:30 Iran Time)
    # New York Close: 21:00 UTC (00:30 next morning Iran Time)
    if time_val_utc < 7.0:
        return False, "خارج از ساعات فعال (قبل از بازگشایی بازار لندن)", {
            "is_open": False,
            "phase": "PRE_LONDON_QUIET",
            "label": "پیش‌گشایش (قبل از بازگشایی لندن)",
            "countdown": "بازگشایی سشن لندن: ساعت ۱۰:۳۰ صبح به وقت ایران"
        }
    elif time_val_utc >= 21.0:
        if weekday == 4:  # Friday after 21:00 UTC
            return False, "پایان معاملات هفته در بازار نیویورک (بازار بسته شد)", {
                "is_open": False,
                "phase": "FRIDAY_CLOSED",
                "label": "پایان معاملات هفته (بسته)",
                "countdown": "بازگشایی مجدد: دوشنبه ساعت ۱۰:۳۰ صبح"
            }
        else:
            return False, "پایان سشن معاملاتی نیویورک (ساعات غیرفعال شبانه)", {
                "is_open": False,
                "phase": "POST_NY_QUIET",
                "label": "پایان سشن نیویورک (آرامش شبانه)",
                "countdown": "بازگشایی سشن لندن: ساعت ۱۰:۳۰ صبح فردا"
            }

    # Active Window (Monday to Friday, 07:00 - 21:00 UTC)
    session_name = "سشن نیویورک" if time_val_utc >= 13.5 else ("هم‌پوشانی طلایی لندن و نیویورک" if time_val_utc >= 12.0 else "سشن لندن")
    return True, f"بازار داوجونز فعال است ({session_name})", {
        "is_open": True,
        "phase": "MARKET_ACTIVE",
        "label": f"بازار فعال ({session_name})",
        "countdown": "سیگنال‌دهی تلگرام مجاز و فعال (از گشایش لندن ۱۰:۳۰ تا پایان نیویورک ۰۰:۳۰)"
    }

def get_us30_telegram_config() -> Dict[str, Any]:
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    auto_pilot = False
    interval_m = 15
    min_score = 70

    if TG_CONFIG_FILE.exists():
        try:
            with open(TG_CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg = json.load(f)
                bot_token = bot_token or cfg.get("bot_token", "")
                chat_id = chat_id or cfg.get("chat_id", "")
                auto_pilot = cfg.get("auto_pilot", False)
                interval_m = cfg.get("interval_minutes", 15)
                min_score = cfg.get("min_score", 70)
        except Exception:
            pass

    market_active, market_reason, session_info = is_us30_market_in_active_session()
    _us30_sentinel_stats["market_active"] = market_active
    _us30_sentinel_stats["market_status"] = session_info.get("label")
    _us30_sentinel_stats["session_info"] = session_info
    _us30_sentinel_stats["market_reason"] = market_reason

    masked = (f"{bot_token[:3]}{'*' * max(4, len(bot_token) - 6)}{bot_token[-3:]}" if len(bot_token) > 8 else ("****" if bot_token else ""))
    j_stats = get_dispatched_journal_stats()
    return {
        "is_configured": bool(bot_token and chat_id),
        "masked_token": masked,
        "chat_id": chat_id,
        "auto_pilot": auto_pilot,
        "interval_minutes": interval_m,
        "min_score": min_score,
        "market_active": market_active,
        "market_status": session_info.get("label"),
        "session_info": session_info,
        "market_reason": market_reason,
        "sentinel_stats": _us30_sentinel_stats,
        "journal_stats": j_stats
    }

def format_us30_composite_telegram(data: Dict[str, Any]) -> str:
    """Format only supplied values; never fabricate market prices or trade levels."""
    tehran_str = datetime.now(timezone(timedelta(hours=3, minutes=30))).strftime("%Y/%m/%d ساعت %H:%M:%S")
    action = str(data.get("action", "WAIT")).upper()
    if action not in {"BUY", "SELL"}:
        return (
            "⚪ <b>داوجونز [#US30] — بدون ستاپ معتبر</b>\n"
            "قیمت یا سطوح معتبر ورود/حدضرر/هدف در دسترس نیست؛ هیچ معامله‌ای پیشنهاد نمی‌شود.\n"
            f"⏰ {tehran_str} (تهران)"
        )
    price = data.get("price")
    sl, tp1, tp2 = data.get("stop_loss"), data.get("tp1"), data.get("tp2")
    if not all(isinstance(v, (int, float)) and float(v) > 0 for v in (price, sl, tp1, tp2)):
        return (
            "⚪ <b>داوجونز [#US30] — دادهٔ ناکافی</b>\n"
            "سطوح معتبر معامله در دسترس نیست؛ سیگنال ارسال نشد.\n"
            f"⏰ {tehran_str} (تهران)"
        )
    direction = "🟢 خرید (LONG)" if action == "BUY" else "🔴 فروش (SHORT)"
    return (
        "💎 <b>سیگنال داوجونز [#US30]</b>\n"
        f"🧭 <b>جهت:</b> {direction}\n"
        f"⏱️ <b>تایم‌فریم:</b> <code>{data.get('interval', '—')}</code>\n"
        f"💰 <b>قیمت:</b> <code>${float(price):,.1f}</code>\n"
        f"🎯 <b>ورود:</b> <code>{data.get('entry_zone', '—')}</code>\n"
        f"🛑 <b>حد ضرر:</b> <code>${float(sl):,.1f}</code>\n"
        f"🎯 <b>TP1:</b> <code>${float(tp1):,.1f}</code>\n"
        f"🎯 <b>TP2:</b> <code>${float(tp2):,.1f}</code>\n"
        f"⏰ <b>زمان:</b> <code>{tehran_str} (تهران)</code>"
    )

@app.get("/api/telegram/config", dependencies=[Depends(verify_admin_auth)])
def telegram_config():
    return get_us30_telegram_config()

@app.post("/api/telegram/config", dependencies=[Depends(verify_admin_auth)])
def save_telegram_config(cfg: US30TelegramConfigRequest):
    try:
        if cfg.bot_token and len(cfg.bot_token.strip()) > 256:
            return JSONResponse(status_code=400, content={"success": False, "message": "طول توکن غیرمجاز است."})
        if cfg.chat_id and len(cfg.chat_id.strip()) > 128:
            return JSONResponse(status_code=400, content={"success": False, "message": "طول شناسهٔ چت غیرمجاز است."})
        if cfg.interval_minutes is not None and not 5 <= int(cfg.interval_minutes) <= 1440:
            return JSONResponse(status_code=400, content={"success": False, "message": "فاصلهٔ ارسال باید بین ۵ تا ۱۴۴۰ دقیقه باشد."})
        if cfg.min_score is not None and not 0 <= int(cfg.min_score) <= 100:
            return JSONResponse(status_code=400, content={"success": False, "message": "حداقل امتیاز باید بین صفر تا ۱۰۰ باشد."})
        existing = {}
        if TG_CONFIG_FILE.exists():
            try:
                with open(TG_CONFIG_FILE, "r", encoding="utf-8") as f:
                    existing = json.load(f)
            except Exception:
                pass

        new_tok = cfg.bot_token.strip() if cfg.bot_token else existing.get("bot_token", "")
        new_chat = cfg.chat_id.strip() if cfg.chat_id else existing.get("chat_id", "")
        auto_pilot_val = cfg.auto_pilot if cfg.auto_pilot is not None else existing.get("auto_pilot", True)
        interval_val = int(cfg.interval_minutes or existing.get("interval_minutes", 15))
        min_score_val = int(cfg.min_score or existing.get("min_score", 70))

        data = {
            "bot_token": new_tok,
            "chat_id": new_chat,
            "auto_pilot": auto_pilot_val,
            "interval_minutes": interval_val,
            "min_score": min_score_val,
            "updated_at": time.strftime("%Y-%m-%d %H:%M:%S UTC")
        }
        with open(TG_CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        return {"success": True, "message": "تنظیمات ربات تلگرام و دیده‌بان خودکار داو جونز با موفقیت ذخیره شد."}
    except Exception as e:
        return JSONResponse(status_code=500, content={"success": False, "message": f"خطا در ذخیره تنظیمات: {str(e)}"})

# (format_us30_master_signal_telegram defined later)
def format_us30_master_signal_telegram(ms_data: Dict[str, Any]) -> str:
    now_utc = datetime.now(timezone.utc)
    tehran_time = now_utc + timedelta(hours=3, minutes=30)
    tehran_str = tehran_time.strftime("%H:%M:%S (%Y/%m/%d)")
    valid_until = (tehran_time + timedelta(hours=2)).strftime("%H:%M")

    p = float(ms_data.get("current_price") or 0.0)
    direction = ms_data.get("direction", "NEUTRAL")
    dir_fa = ms_data.get("direction_fa", "بدون ستاپ معتبر")
    dir_emoji = "🚀" if direction == "BUY" else ("🔻" if direction == "SELL" else "⏸️")
    score = ms_data.get("confluence_score")
    if p <= 10000 or direction not in {"BUY", "SELL"} or score is None or not ms_data.get("tradable"):
        return "⚪ <b>US30 — بدون ستاپ معتبر</b>\nداده یا گارد اجرایی تأیید نشده است؛ پیام معاملاتی ارسال نمی‌شود."
    grade = ms_data.get("confluence_grade", "A+ Institutional Confluence")
    entry_zone = ms_data.get("entry_zone", f"${p-15:,.1f} - ${p:,.1f}")
    sl = float(ms_data.get("stop_loss", p - 65.0))
    sl_dist = ms_data.get("stop_loss_distance", 65)
    tp1 = float(ms_data.get("take_profit_1", p + 115.0))
    tp1_dist = ms_data.get("take_profit_1_distance", 115)
    tp2 = float(ms_data.get("take_profit_2", p + 235.0))
    tp2_dist = ms_data.get("take_profit_2_distance", 235)
    tp3 = float(ms_data.get("take_profit_3", p + 410.0))
    tp3_dist = ms_data.get("take_profit_3_distance", 410)
    lot_size = ms_data.get("recommended_lot_size", "۰.۳۰ لات به ازای هر $10,000")
    rr = ms_data.get("risk_reward", "1 : 3.6")

    checklist = ms_data.get("checklist", [])
    chk_lines = ""
    for c in checklist:
        name = c.get("name", "")
        sig_fa = c.get("signal_fa", "")
        icon = c.get("icon", "🔹")
        sig_fa_clean = sig_fa.replace("<", "&lt;").replace(">", "&gt;")
        chk_lines += f"\n{icon} <b>{name}:</b> <code>{sig_fa_clean}</code>"

    pb = ms_data.get("executive_playbook", "")
    pb_clean = pb.replace("<", "&lt;").replace(">", "&gt;")

    msg = f"""
👑 <b>سیگنال کادر تخصصی همگرا داو جونز | US30 Master Institutional Signal</b>
━━━━━━━━━━━━━━━━━━━━
💰 <b>قیمت لحظه‌ای شاخص داوجونز:</b> <code>${p:,.1f}</code>
🧭 <b>سیگنال سیستم:</b> {dir_emoji} <b>{dir_fa}</b>
⭐ <b>درجه همگرایی ۹ ابزار نهادی:</b> <code>{score}٪</code> ({grade})
⚖️ <b>ریسک به ریوارد:</b> <code>{rr}</code> | <b>حجم پیشنهادی:</b> <code>{lot_size}</code>

⚡ <b>سطوح معاملاتی دقیق (Execution Levels):</b>
⏰ <b>زمان صدور به وقت ایران 🇮🇷:</b> <code>ساعت {tehran_str}</code>
⏳ <b>افق اعتبار ستاپ:</b> <code>تا ساعت {valid_until} به وقت ایران</code>
🔹 <b>محدوده بهینه ورود (Entry):</b> <code>{entry_zone}</code>
🛑 <b>حد ضرر ساختاری (SL):</b> <code>${sl:,.1f} (-{sl_dist} پوینت)</code>
🎯 <b>تارگت اول (TP1):</b> <code>${tp1:,.1f} (+{tp1_dist} پوینت)</code> <i>[سیو ۵۰٪ سود + ریسک‌فری]</i>
🎯 <b>تارگت دوم (TP2):</b> <code>${tp2:,.1f} (+{tp2_dist} پوینت)</code> <i>[سقف دیوارهای نقدینگی BSL]</i>
🎯 <b>تارگت سوم (TP3):</b> <code>${tp3:,.1f} (+{tp3_dist} پوینت)</code> <i>[استخر نهایی وال‌استریت]</i>

📋 <b>تاییدیه ۹ پلتفرم معاملاتی متصل:</b>{chk_lines}

━━━━━━━━━━━━━━━━━━━━
💡 <b>دستورالعمل هوشمند مدیریت معامله:</b>
<i>{pb_clean}</i>
━━━━━━━━━━━━━━━━━━━━
📊 <b>مشاهده آنلاین چارت:</b> <a href="https://www.tradingview.com/chart/?symbol=TVC:DJI">TradingView Chart ↗️</a>
⏰ <i>زمان تحلیل (ایران 🇮🇷): {tehran_str}</i>
"""
    return msg.strip()

DISPATCHED_SIGNALS_FILE = Path(__file__).resolve().parent / "dispatched_signals.jsonl"
_journal_file_lock = threading.Lock()

def append_dispatched_signal(rec: Dict[str, Any]):
    try:
        # Strict Double Guard: Never append any signal to journal when US30 market is closed
        active, reason, _ = is_us30_market_in_active_session()
        if not active:
            print(f"[JOURNAL GUARD] Suppressed signal record because market is closed: {reason}")
            return
        with _journal_file_lock:
            with open(DISPATCHED_SIGNALS_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception as e:
        print(f"Error appending dispatched signal: {e}")

@app.post("/api/telegram/send", dependencies=[Depends(verify_admin_auth)])
def telegram_send(req: US30TelegramSendRequest):
    """Dispatch only a real-index signal that passes the execution guard."""
    try:
        market_active, market_reason, _ = is_us30_market_in_active_session()
        if not market_active:
            return JSONResponse(status_code=409, content={"success": False, "error": "MARKET_CLOSED", "message": market_reason})

        tok = (req.bot_token or os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip()
        chat = (req.chat_id or os.environ.get("TELEGRAM_CHAT_ID") or "").strip()
        if len(tok) > 256 or len(chat) > 128:
            return JSONResponse(status_code=400, content={"success": False, "error": "INVALID_TELEGRAM_CONFIG", "message": "طول توکن یا شناسهٔ چت غیرمجاز است."})
        if not tok or not chat:
            if TG_CONFIG_FILE.exists():
                try:
                    saved = json.loads(TG_CONFIG_FILE.read_text(encoding="utf-8"))
                    tok = tok or str(saved.get("bot_token", "")).strip()
                    chat = chat or str(saved.get("chat_id", "")).strip()
                except Exception:
                    pass
        if not tok or not chat:
            return JSONResponse(status_code=400, content={"success": False, "error": "TELEGRAM_NOT_CONFIGURED", "message": "توکن و شناسهٔ چت تنظیم نشده‌اند."})

        target = str(req.signal_type or "scalp").lower()
        if target not in {"scalp", "swing"}:
            return JSONResponse(status_code=400, content={"success": False, "error": "INVALID_SIGNAL_TYPE", "message": "هر درخواست فقط scalp یا swing را می‌فرستد؛ both باید جداگانه ارسال شود."})

        import us30_unified_signals as uus
        quote_result = _valid_us30_quote(req.interval or "15m")
        if not quote_result.get("ok"):
            return JSONResponse(status_code=503, content={"success": False, "error": "LIVE_QUOTE_UNAVAILABLE", "message": quote_result.get("message") or quote_result.get("error")})
        quote_price = float(quote_result["price"])

        unif = uus.get_us30_unified_signals(quote_price)
        if not isinstance(unif, dict) or not unif.get("ok"):
            return JSONResponse(status_code=503, content={"success": False, "error": "SIGNAL_UNAVAILABLE", "message": (unif or {}).get("message", "سیگنال معتبر تولید نشد.")})
        sig = unif.get("swing" if target == "swing" else "scalp")
        if not isinstance(sig, dict) or sig.get("tradable") is not True or sig.get("direction_code") not in {"LONG", "SHORT"}:
            return JSONResponse(status_code=409, content={"success": False, "error": "SIGNAL_NOT_TRADABLE", "message": "سیگنال خنثی است یا منبع/پلن معتبر ندارد؛ ارسال مسدود شد."})

        try:
            entry = float(sig["entry"])
            sl = float(sig["stop_loss"])
            tp1 = float(sig["tp1"])
            tp2 = float(sig["tp2"])
            tp3 = float(sig["tp3"])
        except (KeyError, TypeError, ValueError):
            return JSONResponse(status_code=409, content={"success": False, "error": "INVALID_TRADE_PLAN", "message": "Entry/SL/TP ناقص است؛ ارسال مسدود شد."})
        if min(entry, sl, tp1, tp2, tp3) <= 0:
            return JSONResponse(status_code=409, content={"success": False, "error": "INVALID_TRADE_LEVELS", "message": "سطوح معامله نامعتبرند."})
        is_long = sig["direction_code"] == "LONG"
        coherent = (sl < entry < tp1 < tp2 < tp3) if is_long else (sl > entry > tp1 > tp2 > tp3)
        if not coherent:
            return JSONResponse(status_code=409, content={"success": False, "error": "INCOHERENT_TRADE_LEVELS", "message": "ترتیب Entry/SL/TP با جهت معامله سازگار نیست."})
        max_entry_deviation = max(abs(entry - sl) * 0.25, quote_price * 0.0005)
        if abs(quote_price - entry) > max_entry_deviation:
            return JSONResponse(status_code=409, content={"success": False, "error": "ENTRY_TOO_FAR_FROM_LIVE_PRICE", "message": "قیمت زنده بیش از حد از ورود برنامه‌ریزی‌شده فاصله دارد؛ برای جلوگیری از ورود دیرهنگام ارسال مسدود شد."})

        # Guard the same timeframe and actual engine analysis; proxy candles never pass.
        guard_interval = "4h" if target == "swing" else "15m"
        try:
            analysis = engine.build_analysis(interval=guard_interval, bars=180, force=True)
        except Exception as exc:
            return JSONResponse(status_code=503, content={"success": False, "error": "GUARD_ANALYSIS_UNAVAILABLE", "message": str(exc)[:200]})
        if not isinstance(analysis, dict) or not analysis.get("ok") or not _analysis_is_real_index(analysis):
            return JSONResponse(status_code=409, content={"success": False, "error": "NON_EXECUTABLE_FEED", "message": "فید کندلی نماد واقعی US30 تأیید نشده است؛ ارسال مسدود شد."})
        engine_signal = analysis.get("signal") or {}
        if int(engine_signal.get("direction", 0) or 0) != (1 if is_long else -1):
            return JSONResponse(status_code=409, content={"success": False, "error": "SIGNAL_DIRECTION_MISMATCH", "message": "جهت سیگنال با تحلیل تازه هم‌خوان نیست؛ ارسال مسدود شد."})
        guard = execguard.evaluate(analysis, interval=guard_interval, balance=10.0, leverage=50.0, lot=0.01)
        if not isinstance(guard, dict) or guard.get("trade_allowed") is not True:
            return JSONResponse(status_code=409, content={"success": False, "error": "EXECUTION_GUARD_BLOCKED", "guard": guard, "message": "گارد ریسک اجازهٔ ارسال این سیگنال را نداد."})

        msg = uus.format_us30_minimal_telegram_signal(sig, is_swing=(target == "swing"))
        if not msg or "بدون معامله" in msg or sig.get("direction_code") == "NEUTRAL":
            return JSONResponse(status_code=409, content={"success": False, "error": "EMPTY_OR_NEUTRAL_MESSAGE", "message": "پیام خنثی یا ناقص ارسال نمی‌شود."})
        res = dispatch_to_telegram_raw(tok, chat, msg)
        if not res.get("ok"):
            return JSONResponse(status_code=502, content={"success": False, "message": res.get("description", "ارسال پیام تلگرام ناموفق بود.")})

        _us30_sentinel_stats["signals_sent_total"] += 1
        _us30_sentinel_stats["last_signal_time"] = time.strftime("%Y-%m-%d %H:%M:%S UTC")
        if not _journal_is_paused:
            now_tehran = datetime.now(timezone.utc) + timedelta(hours=3, minutes=30)
            dispatched_rec = {
                "id": "US30-" + __import__("uuid").uuid4().hex,
                "signal_type": "Swing" if target == "swing" else "Scalp",
                "timeframe": guard_interval,
                "direction": sig["direction_code"],
                "entry": entry, "tp1": tp1, "tp2": tp2, "tp3": tp3, "sl": sl,
                "holding_duration": sig.get("holding_duration"),
                "result": "در جریان (OPEN)", "pnl_pts": 0, "status": "OPEN",
                "data_source": (analysis.get("meta") or {}).get("symbol"),
                "ts": now_tehran.strftime("%Y/%m/%d ساعت %H:%M:%S"),
            }
            append_dispatched_signal(dispatched_rec)
        return {"success": True, "message": f"سیگنال {target} پس از عبور از گارد ارسال شد.", "result": res}
    except Exception as e:
        return JSONResponse(status_code=500, content={"success": False, "error": "TELEGRAM_DISPATCH_FAILED", "message": str(e)[:300]})

@app.post("/api/telegram/test", dependencies=[Depends(verify_admin_auth)])
def telegram_test(req: US30TelegramSendRequest):
    try:
        tok = req.bot_token or os.environ.get("TELEGRAM_BOT_TOKEN") or ""
        chat = req.chat_id or os.environ.get("TELEGRAM_CHAT_ID") or ""
        if not tok or not chat:
            if TG_CONFIG_FILE.exists():
                with open(TG_CONFIG_FILE, "r", encoding="utf-8") as f:
                    saved = json.load(f)
                    tok = tok or saved.get("bot_token", "")
                    chat = chat or saved.get("chat_id", "")

        if not tok or not chat:
            return JSONResponse(status_code=400, content={"success": False, "message": "توکن ربات یا شناسه چت برای ارسال تست موجود نیست. لطفاً ابتدا کادرهای بالا را تکمیل و ذخیره کنید."})

        now_tehran = datetime.now(timezone.utc) + timedelta(hours=3, minutes=30)
        time_str = now_tehran.strftime("%H:%M:%S")
        test_msg = f"""
🦅 <b>آزمون اتصال ربات دیده‌بان هوشمند داو جونز (US30 Sentinel)</b>
━━━━━━━━━━━━━━━━━━━━
✅ اتصال وب‌سرویس و ربات تلگرام با موفقیت برقرار شد.
⏰ <b>زمان تست (ایران 🇮🇷):</b> <code>ساعت {time_str}</code>
📨 <b>وضعیت فید بازار:</b> در این پیام تست نشده است.
ℹ️ این پیام فقط اتصال تلگرام را بررسی می‌کند؛ سلامت فید بازار جداگانه ارزیابی می‌شود.
"""
        res = dispatch_to_telegram_raw(tok, chat, test_msg.strip())
        if not res.get("ok"):
            return JSONResponse(status_code=400, content={"success": False, "message": res.get("description", "ارسال پیام تست ناموفق بود.")})
        return {"success": True, "message": "پیام تست با موفقیت ارسال شد.", "result": res}
    except Exception as e:
        return JSONResponse(status_code=500, content={"success": False, "message": f"خطای سرور: {str(e)}"})

@app.get("/api/journal/live", dependencies=[Depends(verify_admin_auth)])
def journal_live():
    try:
        recs = []
        with _journal_file_lock:
            if DISPATCHED_SIGNALS_FILE.exists():
                with open(DISPATCHED_SIGNALS_FILE, "r", encoding="utf-8") as f:
                    for line in f:
                        if line.strip():
                            try:
                                recs.append(json.loads(line))
                            except Exception:
                                pass

        # Observe the latest quote, but do not infer trade outcomes from one tick.
        # Correct TP/SL lifecycle needs tick ordering, partial fills, spread and slippage.
        try:
            import trendo_engine
            t_data = trendo_engine.get_trendo_us30_live()
            curr_p = float(t_data.get("bid")) if t_data.get("ok") and t_data.get("bid") is not None else None
            if curr_p is not None and curr_p > 10000:
                for rec in recs:
                    if rec.get("status") == "OPEN":
                        rec["last_observed_price"] = curr_p
                        rec["outcome_tracking"] = "NOT_AUTO_RESOLVED_FROM_SINGLE_TICK"
        except Exception:
            pass

        # Sort newest first and assign Row #1 to the newest
        recs_rev = list(reversed(recs))
        for idx, r in enumerate(recs_rev):
            r["row_num"] = idx + 1

        total = len(recs)
        wins = [r for r in recs if r.get("status") == "WIN"]
        losses = [r for r in recs if r.get("status") == "LOSS"]

        total_tp = sum(r.get("pnl_pts", 0) for r in wins)
        total_sl = abs(sum(r.get("pnl_pts", 0) for r in losses))
        net_pts = total_tp - total_sl
        win_rate = round((len(wins) / total) * 100, 1) if total > 0 else 0.0

        # Dedicated 1m Sniper Micro-Scalp Statistics
        sniper_recs = [r for r in recs if r.get("timeframe") == "1m" or "اسکالپ" in str(r.get("signal_type", ""))]
        sn_tot = len(sniper_recs)
        sn_wins = [r for r in sniper_recs if r.get("status") == "WIN"]
        sn_loss = [r for r in sniper_recs if r.get("status") == "LOSS"]
        sn_tp_pts = sum(r.get("pnl_pts", 0) for r in sn_wins)
        sn_sl_pts = abs(sum(r.get("pnl_pts", 0) for r in sn_loss))
        sn_net_pts = sn_tp_pts - sn_sl_pts
        sn_wr = round((len(sn_wins) / sn_tot) * 100, 1) if sn_tot > 0 else 0.0
        sn_net_usd = round(sn_net_pts * 0.10, 2)
        sn_pf = round(sn_tp_pts / max(1.0, float(sn_sl_pts)), 2) if sn_sl_pts > 0 else (round(sn_tp_pts / 1.0, 2) if sn_tp_pts > 0 else 0.0)

        return {
            "ok": True,
            "is_paused": _journal_is_paused,
            "records": recs_rev,
            "stats": {
                "total_signals": total,
                "total_tp_pts": total_tp,
                "total_sl_pts": total_sl,
                "net_pts": net_pts,
                "win_rate": win_rate,
                "wins_count": len(wins),
                "losses_count": len(losses)
            },
            "sniper_1m_stats": {
                "total": sn_tot,
                "wins": len(sn_wins),
                "losses": len(sn_loss),
                "win_rate": sn_wr,
                "net_pts": sn_net_pts,
                "net_usd_001_lot": sn_net_usd,
                "profit_factor": sn_pf,
                "total_tp_pts": sn_tp_pts,
                "total_sl_pts": sn_sl_pts,
                "safe_sl_desc": "۱۲ تا ۱۴ پوینت ($۱.۲۰ - $۱.۴۰)",
                "target_desc": "تارگت اول +۲۴ pt | تارگت دوم +۴۸ pt",
                "grade": "GRADE A+ (اعتبار نهادی)"
            }
        }
    except Exception as e:
        return {"ok": False, "records": [], "stats": {}, "error": str(e)}

_journal_is_paused = False

@app.post("/api/journal/toggle-pause", dependencies=[Depends(verify_admin_auth)])
def journal_toggle_pause():
    global _journal_is_paused
    _journal_is_paused = not _journal_is_paused
    status_label = "متوقف‌شده" if _journal_is_paused else "فعال"
    return {
        "ok": True,
        "is_paused": _journal_is_paused,
        "message": f"وضعیت ثبت سیگنال ژورنال به حالت «{status_label}» تغییر یافت."
    }

@app.post("/api/journal/reset", dependencies=[Depends(verify_admin_auth)])
def journal_reset():
    try:
        if DISPATCHED_SIGNALS_FILE.exists():
            with open(DISPATCHED_SIGNALS_FILE, "w", encoding="utf-8") as f:
                f.write("")
        return {
            "ok": True,
            "message": "تمام سوابق سیگنال‌های ژورنال با موفقیت ریست و پاکسازی شدند.",
            "stats": {
                "total_signals": 0,
                "total_tp_pts": 0,
                "total_sl_pts": 0,
                "net_pts": 0,
                "win_rate": 0.0,
                "wins_count": 0,
                "losses_count": 0
            },
            "sniper_1m_stats": {
                "total": 0,
                "wins": 0,
                "losses": 0,
                "win_rate": 0.0,
                "net_pts": 0,
                "net_usd_001_lot": 0.0,
                "profit_factor": 0.0,
                "total_tp_pts": 0,
                "total_sl_pts": 0,
                "safe_sl_desc": "۱۲ تا ۱۴ پوینت ($۱.۲۰ - $۱.۴۰)",
                "target_desc": "تارگت اول +۲۴ pt | تارگت دوم +۴۸ pt",
                "grade": "GRADE A+ (اعتبار نهادی)"
            },
            "records": []
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}

@app.post("/api/telegram/toggle-autopilot", dependencies=[Depends(verify_admin_auth)])
def telegram_toggle_autopilot():
    try:
        if os.environ.get("ENABLE_TELEGRAM_AUTOPILOT", "0").strip() != "1":
            return {"ok": False, "is_running": False, "error": "AUTOPILOT_DISABLED_BY_ENV", "message": "ارسال خودکار در تنظیمات سرور غیرفعال است؛ ابتدا فید واقعی و گارد ریسک را تأیید کنید."}
        current_state = _us30_sentinel_stats.get("is_running", False)
        new_state = not current_state
        _us30_sentinel_stats["is_running"] = new_state

        if TG_CONFIG_FILE.exists():
            try:
                with open(TG_CONFIG_FILE, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                cfg["auto_pilot"] = new_state
                with open(TG_CONFIG_FILE, "w", encoding="utf-8") as f:
                    json.dump(cfg, f, ensure_ascii=False, indent=2)
            except Exception:
                pass

        status_text = "فعال و در حال ارسال" if new_state else "متوقف شده"
        return {
            "ok": True,
            "is_running": new_state,
            "message": f"دیده‌بان تلگرام اکنون «{status_text}» است."
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}

@app.get("/api/telegram/interactive-status", dependencies=[Depends(verify_admin_auth)])
def telegram_interactive_status():
    return {
        "ok": True,
        "interactive_stats": _us30_interactive_bot_stats,
        "sentinel_stats": _us30_sentinel_stats
    }

@app.post("/api/advisor/ask")
def advisor_ask_question(req: DowAdvisorQuestionRequest):
    try:
        from dow_advisor_engine import DowAIAdvisor
        answer = DowAIAdvisor.answer_question(req.question, req.price)
        return {
            "ok": True,
            "question": req.question,
            "answer": answer
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}




_composite_signal_cache: Dict[str, Dict[str, Any]] = {}

_LOCKED_COMPOSITE_SETUPS: Dict[str, Dict[str, Any]] = {}



@app.get("/api/trendo/live")
def trendo_live_quote():
    try:
        import trendo_engine
        return trendo_engine.get_trendo_us30_live()
    except Exception as e:
        return {"ok": False, "error": str(e)}

@app.get("/api/trendo/levels")
def trendo_levels(direction: str = Query("BUY")):
    try:
        import trendo_engine
        return trendo_engine.compute_trendo_sniper_levels(direction)
    except Exception as e:
        return {"ok": False, "error": str(e)}

@app.get("/api/dow/composite-signal")
def dow_composite_signal(
    interval: str = Query("1m"),
    broker: str = Query("trendo", description="trendo or forexcom"),
):
    """Build a conservative signal from the real OHLCV analysis; no synthetic votes."""
    allowed = {"1m", "5m", "15m", "30m", "1h", "4h", "1d"}
    interval = interval if interval in allowed else "1h"
    broker = str(broker or "trendo").lower()
    if broker not in {"trendo", "forexcom"}:
        broker = "trendo"
    try:
        analysis = engine.build_analysis(interval=interval, bars=180, force=False)
    except Exception as exc:
        return {
            "ok": False, "action": "WAIT", "action_fa": "دادهٔ بازار در دسترس نیست؛ منتظر بمانید",
            "error": "ANALYSIS_UNAVAILABLE", "detail": str(exc), "interval": interval,
        }

    if not isinstance(analysis, dict) or not analysis.get("ok"):
        return {"ok": False, "action": "WAIT", "action_fa": "تحلیل معتبر در دسترس نیست", "interval": interval}
    try:
        price = float((analysis.get("price") or {}).get("last"))
        signal = analysis.get("signal") or {}
        direction = int(signal.get("direction", 0) or 0)
        score = float(signal.get("score", 0) or 0)
        plan = signal.get("plan") if isinstance(signal.get("plan"), dict) else {}
        entry = float(plan.get("entry")) if plan.get("entry") is not None else None
        sl = float(plan.get("stop")) if plan.get("stop") is not None else None
        tp1 = float(plan.get("tp1")) if plan.get("tp1") is not None else None
        tp2 = float(plan.get("tp2")) if plan.get("tp2") is not None else None
        tp3 = float(plan.get("tp3")) if plan.get("tp3") is not None else None
    except (TypeError, ValueError, AttributeError):
        return {"ok": False, "action": "WAIT", "action_fa": "قیمت یا پلن تحلیل نامعتبر است", "interval": interval}

    if not price or price <= 10000:
        return {"ok": False, "action": "WAIT", "action_fa": "قیمت معتبر داوجونز در دسترس نیست", "interval": interval}

    levels_ok = all(v is not None and v > 0 for v in (entry, sl, tp1, tp2, tp3))
    if direction > 0:
        levels_ok = levels_ok and sl < entry < tp1 < tp2 < tp3
    elif direction < 0:
        levels_ok = levels_ok and sl > entry > tp1 > tp2 > tp3
    else:
        levels_ok = False

    # A direction alone is not enough: require a coherent plan and reasonable confidence.
    real_index_source = _analysis_is_real_index(analysis)
    timeframe_validated = interval not in getattr(execguard, "BAD_INTERVALS", set())
    candidate_actionable = bool(real_index_source and timeframe_validated and levels_ok and score >= 65)
    guard_result = None
    if candidate_actionable:
        try:
            guard_result = execguard.evaluate(analysis, interval=interval, balance=10.0, leverage=50.0, lot=0.01)
        except Exception as exc:
            guard_result = {"trade_allowed": False, "reason": str(exc)[:200]}
    actionable = bool(candidate_actionable and isinstance(guard_result, dict) and guard_result.get("trade_allowed") is True)
    action = ("BUY" if direction > 0 else "SELL") if actionable else "WAIT"
    action_fa = (
        "🟢 خرید بر اساس تحلیل OHLCV" if action == "BUY" else
        "🔴 فروش بر اساس تحلیل OHLCV" if action == "SELL" else
        "⚪ خنثی / داده یا تأیید کافی نیست — بدون معامله"
    )
    checklist = []
    for part in signal.get("parts", [])[:8]:
        if isinstance(part, dict):
            checklist.append({"name": str(part.get("name", "جزء تحلیل")), "status": "neutral", "badge": "ℹ️ تحلیل تکنیکال", "detail": str(part.get("detail", ""))})
    validation = {
        "is_vetoed": not actionable,
        "filters_passed": "فقط تحلیل OHLCV؛ تأیید مستقل داده‌های نهادی در دسترس نیست",
        "passed_count": 1 if actionable else 0,
        "filters": [
            {"name": "قیمت/کندل", "status": "pass", "badge": "قابل‌خواندن", "detail": "تحلیل از خروجی موتور OHLCV"},
            {"name": "تأیید مستقل نهادی", "status": "neutral", "badge": "تأیید نشده", "detail": "دادهٔ زندهٔ معتبر برای این فیلترها تأیید نشده است"},
        ],
        "heavyweights": {"status": "neutral", "badge": "داده در دسترس نیست", "members": [], "net_dow_pts": None},
    }
    risk = abs(entry - sl) if levels_ok else None
    rr = (abs(tp2 - entry) / risk) if risk else None
    fmt = lambda v: f"${v:,.1f}" if isinstance(v, (int, float)) else "—"
    return {
        "ok": True,
        "tradable": actionable,
        "interval": interval,
        "broker": broker,
        "price": price,
        "action": action,
        "action_fa": action_fa,
        "color": "#00e676" if action == "BUY" else ("#ff3366" if action == "SELL" else "#ffd166"),
        "grade": signal.get("grade", "D") if actionable else "—",
        "total_confluence": round(score, 1) if actionable else 0,
        "score": round(score, 1) if actionable else 0,
        "risk_reward": f"1:{rr:.2f}" if rr else "—",
        "setup_name": f"تحلیل تکنیکال US30 · {interval}",
        "entry_price": entry if actionable else None,
        "entry_zone": fmt(entry) if actionable else "—",
        "stop_loss": sl if actionable else None,
        "stop_loss_pts": round(abs(entry - sl), 1) if actionable else None,
        "tp1": tp1 if actionable else None,
        "tp1_pts": round(abs(tp1 - entry), 1) if actionable else None,
        "tp2": tp2 if actionable else None,
        "tp2_pts": round(abs(tp2 - entry), 1) if actionable else None,
        "tp3": tp3 if actionable else None,
        "tp3_pts": round(abs(tp3 - entry), 1) if actionable else None,
        "checklist": checklist,
        "validation": validation,
        "execution_guard": guard_result or {"ok": False, "trade_allowed": False, "reason": "سیگنال یا تایم‌فریم شرایط لازم را ندارد."},
        "triggers": {"silver_bullet": {"badge": "دادهٔ زنده تأیید نشده", "color": "#ffd166", "is_active": False}, "ema_fan": {"badge": "از تحلیل OHLCV استفاده کنید", "color": "#ffd166"}, "adr": {"badge": "دادهٔ معتبر در دسترس نیست", "color": "#ffd166"}},
        "smt_and_sweep": {"ok": False, "message": "واگرایی و سطوح نقدینگی تا زمان دریافت دادهٔ هم‌زمان واقعی محاسبه نمی‌شوند."},
        "source": (analysis.get("meta") or {}).get("provider", "unknown"),
        "source_note": (analysis.get("meta") or {}).get("source_note", ""),
        "real_index_source": real_index_source,
        "signal_note": "" if actionable else ("منبع کندل نماد اجرایی US30 نیست، تایم‌فریم تأیید نشده یا پلن/امتیاز کافی نیست؛ سیگنال معاملاتی صادر نشد."),
        "generated": (analysis.get("meta") or {}).get("generated"),
    }


@app.get("/api/dow/leaders")
def dow_leaders():
    return _unavailable_module("dow_leaders", "محاسبهٔ اثر اجزای داو تا زمانی که تمام قیمت‌های اجزا از منبع معتبر دریافت نشوند، غیرفعال است.")


@app.get("/api/dow/elite-suite")
def dow_elite_suite():
    return {
        "ok": False,
        "error": "SYNTHETIC_MODULES_DISABLED",
        "message": "ماژول‌های ORB، گاما/آپشن، اینترنالز و جوداس تا اتصال به دادهٔ واقعی غیرفعال‌اند.",
        "modules": {
            "killzones_orb": {"ok": False, "message": "دادهٔ کندل ۱۵ دقیقهٔ واقعی برای ORB لازم است."},
            "gex_options": {"ok": False, "message": "زنجیرهٔ آپشن/دادهٔ GEX واقعی متصل نیست."},
            "nyse_internals": {"ok": False, "message": "فید زندهٔ TICK/TRIN/A-D متصل نیست."},
            "liquidity_judas": {"ok": False, "message": "PDH/PDL باید از کندل‌های واقعی محاسبه شود."},
        },
    }

@app.get("/api/dow/triggers")
def dow_triggers(interval: str = Query("1h")):
    try:
        analysis = engine.build_analysis(interval=interval, bars=180, force=False)
        candles = analysis.get("candles", []) if isinstance(analysis, dict) else []
        if not analysis.get("ok") or len(candles) < 22:
            raise RuntimeError("برای محاسبهٔ تریگرها حداقل ۲۲ کندل معتبر لازم است")
        closes = [float(c["c"]) for c in candles if c.get("c") is not None]
        if len(closes) < 22:
            raise RuntimeError("دادهٔ کندل کافی نیست")
        def _ema(vals, period):
            alpha = 2.0 / (period + 1.0)
            result = vals[0]
            for value in vals[1:]:
                result = alpha * value + (1.0 - alpha) * result
            return result
        e9, e21 = _ema(closes, 9), _ema(closes, 21)
        return {"ok": True, "interval": interval, "ema_fan": {"ema9": round(e9, 2), "ema21": round(e21, 2), "direction": "LONG" if e9 > e21 else ("SHORT" if e9 < e21 else "NEUTRAL")}, "silver_bullet": {"is_active": False, "badge": "زمان‌بندی به‌تنهایی سیگنال نیست", "color": "#ffd166"}, "adr": {"ok": False, "badge": "دادهٔ ADR واقعی در دسترس نیست", "color": "#ffd166"}}
    except Exception as exc:
        return {"ok": False, "error": "TRIGGER_DATA_UNAVAILABLE", "message": str(exc)}

@app.get("/api/dow/killzones-orb")
def dow_killzones_orb():
    return _unavailable_module("killzones_orb", "ORB بدون کندل‌های واقعی سشن جاری محاسبه نمی‌شود.")

@app.get("/api/dow/gex-options")
def dow_gex_options():
    return _unavailable_module("gex_options", "زنجیرهٔ آپشن و دادهٔ GEX زنده متصل نیست؛ مقادیر تخمینی نمایش داده نمی‌شوند.")

@app.get("/api/dow/nyse-internals")
def dow_nyse_internals():
    return _unavailable_module("nyse_internals", "فید واقعی NYSE TICK/TRIN/advance-decline متصل نیست.")

@app.get("/api/dow/liquidity-judas")
def dow_liquidity_judas():
    return _unavailable_module("liquidity_judas", "سطوح PDH/PDL و تشخیص Judas باید از OHLCV واقعی سشن محاسبه شوند.")

@app.get("/api/dow/heavyweights")
def dow_heavyweights():
    return _unavailable_module("dow_heavyweights", "دادهٔ اجزای داوجونز نباید با قیمت‌های جایگزین تخمینی تکمیل شود؛ منبع معتبر همهٔ نمادها در دسترس نیست.")


@app.get("/api/dow/cot")
@app.get("/api/dow/cot-report")
def dow_cot_report():
    try:
        import cftc_cot_engine as cot_engine
        return cot_engine.get_us30_cot_report()
    except Exception as e:
        return {"ok": False, "error": str(e)}

@app.get("/api/dow/bookmap")
def dow_bookmap():
    return _unavailable_module("bookmap", "فید واقعی Level 2/3 یا order book متصل نیست؛ نقشهٔ نقدینگی شبیه‌سازی‌شده نمایش داده نمی‌شود.")


@app.get("/api/dow/ninjatrader")
def dow_ninjatrader():
    return _unavailable_module("ninjatrader", "اتصال زندهٔ NinjaTrader وجود ندارد؛ دادهٔ شبیه‌سازی‌شده نمایش داده نمی‌شود.")


@app.get("/api/dow/atas")
def dow_atas():
    return _unavailable_module("atas", "اتصال زندهٔ ATAS وجود ندارد؛ دادهٔ شبیه‌سازی‌شده نمایش داده نمی‌شود.")


@app.get("/api/dow/quantower")
def dow_quantower():
    return _unavailable_module("quantower", "اتصال زندهٔ Quantower وجود ندارد؛ دادهٔ شبیه‌سازی‌شده نمایش داده نمی‌شود.")


@app.get("/api/dow/geopolitics")
def dow_geopolitics():
    return _unavailable_module("geopolitics", "فید خبری و محاسبهٔ زندهٔ GPR متصل نیست؛ امتیاز ثابت/شبیه‌سازی‌شده ارائه نمی‌شود.")

@app.get("/api/dow/sierrachart")
def dow_sierrachart_endpoint(timeframe: str = Query("15m")):
    return _unavailable_module("sierrachart", "اتصال زندهٔ Sierra Chart وجود ندارد؛ دادهٔ شبیه‌سازی‌شده نمایش داده نمی‌شود.")


@app.get("/api/dow/master-signal")
def dow_master_signal_endpoint():
    return _unavailable_module("master_signal", "سیگنال چندپلتفرمی بدون فیدهای واقعی NinjaTrader/ATAS/Quantower قابل تأیید نیست.")


@app.get("/api/dow/killzone")
def dow_killzone():
    try:
        import elite_modules as elite
        return elite.get_session_killzone_status()
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.get("/api/dow/divisor-impact")
def dow_divisor_impact():
    return _unavailable_module("divisor_impact", "اثر اجزای شاخص فقط وقتی محاسبه می‌شود که قیمت فعلی و قبلی همهٔ اجزا معتبر باشد.")


@app.get("/api/dow/moc-imbalance")
def dow_moc_imbalance():
    return _unavailable_module("moc_imbalance", "فید زندهٔ سفارشات حراج پایانی MOC متصل نیست؛ عدم تعادل ساختگی گزارش نمی‌شود.")


@app.get("/api/dow/smt-and-sweep")
def dow_smt_and_sweep():
    return _unavailable_module("smt_and_sweep", "نسخهٔ فعلی از بازده‌های ثابت/ساختگی SPX و NDX استفاده می‌کرد؛ تا دریافت کندل‌های هم‌زمان واقعی خروجی سیگنال‌ساز غیرفعال است.")


# In-memory journal store with thread safety
_JOURNAL_LOCK = threading.Lock()
_JOURNAL_STORE: List[Dict[str, Any]] = []

@app.get("/api/journal")
@app.get("/api/journal/live")
@app.get("/api/journal/stats")
def get_journal_records():
    """Returns actual recorded signal lifecycle records cleanly."""
    with _JOURNAL_LOCK:
        wins = sum(1 for r in _JOURNAL_STORE if r.get("status") in ["WIN", "TP1", "TP2", "TP3"])
        losses = sum(1 for r in _JOURNAL_STORE if r.get("status") in ["LOSS", "SL"])
        total = len(_JOURNAL_STORE)
        wr = round((wins / total * 100), 1) if total > 0 else 0.0
        return {
            "ok": True,
            "total_signals": total,
            "win_rate": wr,
            "wins": wins,
            "losses": losses,
            "records": _JOURNAL_STORE[-50:] # last 50 trades
        }


def get_dashboard_html() -> str:
    p = APP_DIR / "index.html"
    if p.exists():
        return p.read_text(encoding="utf-8")
    return "<html><body><h1>US30 Dashboard</h1><p>index.html not found.</p></body></html>"


@app.api_route("/", methods=["GET", "HEAD"], response_class=HTMLResponse)
def index():
    return HTMLResponse(get_dashboard_html(), status_code=200)



def us30_sentinel_auto_loop():
    time.sleep(15)
    while True:
        if os.environ.get("ENABLE_TELEGRAM_AUTOPILOT", "0").strip() != "1" or not os.environ.get("ADMIN_SECRET_KEY", "").strip():
            time.sleep(30)
            continue
        try:
            # 1. Institutional Session Guard: London Open (07:00 UTC) to New York Close (21:00 UTC) on Weekdays
            market_active, market_reason, session_info = is_us30_market_in_active_session()
            tehran_now = datetime.now(timezone(timedelta(hours=3, minutes=30)))
            _us30_sentinel_stats["last_check_utc"] = time.strftime("%Y-%m-%d %H:%M:%S UTC")
            _us30_sentinel_stats["last_check_tehran"] = tehran_now.strftime("%Y/%m/%d %H:%M:%S")
            _us30_sentinel_stats["market_active"] = market_active
            _us30_sentinel_stats["market_status"] = session_info.get("label")
            _us30_sentinel_stats["session_info"] = session_info
            _us30_sentinel_stats["skip_reason"] = market_reason

            if not market_active:
                # Strictly suppress all signals outside London Open -> NY Close
                time.sleep(60)
                continue

            cfg = get_us30_telegram_config()
            real_tok = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
            real_chat = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
            if not real_tok or not real_chat:
                if TG_CONFIG_FILE.exists():
                    try:
                        with open(TG_CONFIG_FILE, "r", encoding="utf-8") as f:
                            saved = json.load(f)
                            real_tok = real_tok or saved.get("bot_token", "")
                            real_chat = real_chat or saved.get("chat_id", "")
                    except Exception:
                        pass

            if real_tok and real_chat and cfg.get("auto_pilot", False) and _us30_sentinel_stats.get("is_running", True):
                now_ts = time.time()
                last_sent = _us30_sentinel_stats.get("last_sent_epoch", 0)
                interval_secs = cfg.get("interval_minutes", 15) * 60
                min_score = cfg.get("min_score", 70)

                if now_ts - last_sent > interval_secs:
                    # Multi-Timeframe Scanner: Scan 1m, 5m, 15m, 1h, 4h
                    # Only daily signals are currently supported by the validated quality gate.
                    candidate_tf = ["1d"]
                    best_sig = None
                    best_score = -1
                    best_tf = "1d"

                    for tf in candidate_tf:
                        try:
                            s_data = dow_composite_signal(tf, broker="trendo")
                            sc = int(s_data.get("score", 0) or 0)
                            act = s_data.get("action", "WAIT")
                            if s_data.get("ok") and s_data.get("real_index_source") is True and act in ["BUY", "SELL"] and sc >= min_score and sc > best_score:
                                best_score = sc
                                best_sig = s_data
                                best_tf = tf
                        except Exception:
                            pass

                    if best_sig and best_tf != "1d":
                        best_sig = None
                    live_quote_for_dispatch = _valid_us30_quote(best_tf) if best_sig else {"ok": False}
                    if best_sig and not live_quote_for_dispatch.get("ok"):
                        best_sig = None
                    if best_sig:
                        live_dispatch_price = float(live_quote_for_dispatch["price"])
                        try:
                            guard_analysis = engine.build_analysis(interval=best_tf, bars=180, force=True)
                            if not isinstance(guard_analysis, dict) or not guard_analysis.get("ok") or not _analysis_is_real_index(guard_analysis):
                                best_sig = None
                            else:
                                gs = guard_analysis.get("signal") or {}
                                expected_dir = 1 if best_sig.get("action") == "BUY" else -1
                                plan = gs.get("plan") or {}
                                try:
                                    entry_for_guard = float(plan.get("entry"))
                                    stop_for_guard = float(plan.get("stop"))
                                except (TypeError, ValueError):
                                    entry_for_guard = stop_for_guard = 0.0
                                deviation_limit = max(abs(entry_for_guard - stop_for_guard) * 0.25, live_dispatch_price * 0.0005)
                                if int(gs.get("direction", 0) or 0) != expected_dir or entry_for_guard <= 0 or abs(live_dispatch_price - entry_for_guard) > deviation_limit:
                                    best_sig = None
                                else:
                                    guard_result = execguard.evaluate(guard_analysis, interval=best_tf, balance=10.0, leverage=50.0, lot=0.01)
                                    if not isinstance(guard_result, dict) or guard_result.get("trade_allowed") is not True:
                                        best_sig = None
                        except Exception:
                            best_sig = None
                    if best_sig:
                        import us30_unified_signals as uus
                        if best_tf == "1m":
                            unif = uus.get_us30_unified_signals()
                            sig_body = unif.get("scalp", {})
                            msg = uus.format_us30_clean_telegram_signal(sig_body, is_swing=False)
                            entry_val = sig_body.get("entry", best_sig.get("price"))
                            sl_val = sig_body.get("stop_loss", best_sig.get("stop_loss"))
                            tp1_val = sig_body.get("tp1", best_sig.get("tp1"))
                            tp2_val = sig_body.get("tp2", best_sig.get("tp2"))
                            dur_val = "۲ الی ۱۰ دقیقه (خروج سریع)"
                        elif best_tf == "4h":
                            unif = uus.get_us30_unified_signals()
                            sig_body = unif.get("swing", {})
                            msg = uus.format_us30_clean_telegram_signal(sig_body, is_swing=True)
                            entry_val = sig_body.get("entry", best_sig.get("price"))
                            sl_val = sig_body.get("stop_loss", best_sig.get("stop_loss"))
                            tp1_val = sig_body.get("tp1", best_sig.get("tp1"))
                            tp2_val = sig_body.get("tp2", best_sig.get("tp2"))
                            tp3_val = sig_body.get("tp3", best_sig.get("tp3", 0))
                            dur_val = "۲ تا ۵ روز"
                        else:
                            entry_val = best_sig.get("price")
                            sl_val = best_sig.get("stop_loss")
                            tp1_val = best_sig.get("tp1")
                            tp2_val = best_sig.get("tp2")
                            tp3_val = best_sig.get("tp3", 0)
                            dur_val = "۱۵ دقیقه تا ۱ ساعت"
                            cur_p = live_dispatch_price
                            tehran_t = datetime.now(timezone(timedelta(hours=3, minutes=30))).strftime("%Y/%m/%d ساعت %H:%M:%S")
                            msg = f"""💎 <b>سیگنال داوجونز [#US30]</b>
━━━━━━━━━━━━━━━━━━━━
🏢 <b>بروکر مرجع:</b> <code>ترندو آنلاین (Trendo Live Feed)</code>
🧭 <b>جهت معامله:</b> {'🟢 خرید (LONG)' if best_sig.get('action') == 'BUY' else '🔴 فروش (SHORT)'}
⏱️ <b>تایم‌فریم:</b> <code>{best_tf}</code>
💰 <b>قیمت لحظه صدور:</b> <code>${cur_p:,.1f}</code>
🎯 <b>قیمت ورود قطعی:</b> <code>{best_sig.get('entry_zone')}</code>
🛑 <b>حد ضرر (SL):</b> <code>${sl_val:,.1f} (-{best_sig.get('stop_loss_pts')} pt)</code>
🎯 <b>حد سود اول (TP1):</b> <code>${tp1_val:,.1f} (+{best_sig.get('tp1_pts')} pt)</code>
🎯 <b>حد سود دوم (TP2):</b> <code>${tp2_val:,.1f} (+{best_sig.get('tp2_pts')} pt)</code>"""
                            if tp3_val > 0:
                                msg += f"\n🎯 <b>حد سود سوم (TP3):</b> <code>${tp3_val:,.1f}</code>"
                            msg += f"""
📦 <b>حجم پوزیشن:</b> <code>پیش از اجرا با مشخصات قرارداد، ارزش پوینت، spread و مارجین بروکر محاسبه شود.</code>
⏰ <b>تاریخ و ساعت صدور:</b> <code>{tehran_t} (ایران 🇮🇷)</code>
⏳ <b>انقضا / اعتبار ستاپ:</b> <code>تا زمان برخورد به حد سود یا حد ضرر</code>
━━━━━━━━━━━━━━━━━━━━"""

                        res = dispatch_to_telegram_raw(real_tok, real_chat, msg)
                        if res.get("ok"):
                            _us30_sentinel_stats["signals_sent_total"] += 1
                            _us30_sentinel_stats["last_sent_epoch"] = now_ts
                            _us30_sentinel_stats["last_signal_time"] = time.strftime("%Y-%m-%d %H:%M:%S UTC")

                            # AUTOMATICALLY REGISTER IN JOURNAL!
                            tehran_now = datetime.now(timezone(timedelta(hours=3, minutes=30)))
                            journal_rec = {
                                "id": "US30-" + __import__("uuid").uuid4().hex,
                                "time": tehran_now.strftime("%H:%M:%S"),
                                "date": tehran_now.strftime("%Y/%m/%d"),
                                "signal_type": "میکرو-اسکالپ تک‌تیرانداز 1m" if best_tf == "1m" else ("سوئینگ جامع 4H" if best_tf == "4h" else f"اسکالپ {best_tf}"),
                                "timeframe": best_tf,
                                "direction": best_sig.get("action", "BUY"),
                                "entry": entry_val,
                                "sl": sl_val,
                                "tp1": tp1_val,
                                "tp2": tp2_val,
                                "tp3": tp3_val,
                                "holding_duration": dur_val,
                                "status": "OPEN",
                                "pnl_pts": 0,
                                "lot_size": 0.01,
                                "broker": "Trendo",
                                "ts": tehran_now.strftime("%Y/%m/%d ساعت %H:%M:%S")
                            }
                            append_dispatched_signal(journal_rec)
        except Exception as e:
            _us30_sentinel_stats["last_error"] = str(e)
        time.sleep(60)

def us30_telegram_interactive_poller():
    """
    Two-way interactive Telegram bot polling daemon.
    Listens for user commands (/start, /status, /scalp, /cot, /analysis360)
    and natural-language inquiries, passing them through DowAIAdvisor.
    """
    time.sleep(12)
    last_update_id = 0
    while True:
        try:
            if os.environ.get("ENABLE_TELEGRAM_INTERACTIVE_BOT", "0").strip() != "1" or not os.environ.get("ADMIN_SECRET_KEY", "").strip():
                time.sleep(30)
                continue
            bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
            if not bot_token and TG_CONFIG_FILE.exists():
                try:
                    with open(TG_CONFIG_FILE, "r", encoding="utf-8") as f:
                        bot_token = json.load(f).get("bot_token", "").strip()
                except Exception:
                    pass

            if not bot_token:
                time.sleep(20)
                continue

            _us30_interactive_bot_stats["last_poll_utc"] = time.strftime("%Y-%m-%d %H:%M:%S UTC")

            # Call Telegram getUpdates
            url = f"https://api.telegram.org/bot{bot_token}/getUpdates?offset={last_update_id}&timeout=15"
            req = urllib.request.Request(url, headers={"User-Agent": "US30-Sentinel-Bot/2.0"})
            with urllib.request.urlopen(req, timeout=25) as resp:
                data = json.loads(resp.read().decode())
                if data.get("ok"):
                    updates = data.get("result", [])
                    for u in updates:
                        up_id = u.get("update_id", 0)
                        last_update_id = max(last_update_id, up_id + 1)
                        _us30_interactive_bot_stats["last_update_id"] = last_update_id

                        msg_obj = u.get("message") or u.get("channel_post")
                        if not msg_obj:
                            continue

                        chat = msg_obj.get("chat", {})
                        chat_id = str(chat.get("id", ""))
                        text = (msg_obj.get("text") or "").strip()

                        if not chat_id or not text:
                            continue

                        from dow_advisor_engine import DowAIAdvisor

                        reply_text = ""
                        clean_cmd = text.lower().split("@")[0].strip()

                        if clean_cmd in ["/start", "/help", "راهنما", "دستورات"]:
                            reply_text = """👋 <b>به ربات هوشمند تعاملی سنتینل داوجونز خوش آمدید!</b>
━━━━━━━━━━━━━━━━━━━━
من مشاور هوشمند ۲۴ ساعته وال‌استریت برای نماد <b>US30</b> هستم. شما می‌توانید در هر لحظه دستورات زیر را ارسال کنید یا هر سوالی درباره بازار بپرسید:

⚡ <b>دستورات سریع:</b>
• <code>/status</code> 👈 نرخ لحظه‌ای Bid/Ask و اسپرد ترندو + ساعت و وضعیت سشن
• <code>/scalp</code> 👈 آخرین ستاپ ۱ دقیقه‌ای میکرو اسکالپ با استاپ ۱۲-۱۴ پوینت برای حساب ۱۰ دلاری
• <code>/cot</code> 👈 گزارش رسمی تعهدات معامله‌گران نهادی وال‌استریت (CFTC CoT)
• <code>/analysis360</code> 👈 خلاصه ساختار بازار، ترازهای نقدینگی و سطوح عرضه و تقاضا

💡 <b>چت هوشمند و پرسش آزاد:</b>
می‌توانید هر سوالی را به زبان فارسی بفرستید! برای مثال:
  • <i>«الان بخرم یا بفروشم؟»</i>
  • <i>«بین بوک‌مپ و اوراق قرضه تضاد هست، چکار کنم؟»</i>
  • <i>«دو تا استاپ خوردم اعصابم خورده»</i>
  • <i>«فرمول مقسوم‌علیه داوجونز و تاثیر UNH چیه؟»</i>
━━━━━━━━━━━━━━━━━━━━"""
                        elif clean_cmd == "/status":
                            reply_text = DowAIAdvisor.get_quick_status_summary()
                        elif clean_cmd == "/scalp":
                            reply_text = DowAIAdvisor.get_quick_scalp_summary()
                        elif clean_cmd == "/cot":
                            reply_text = DowAIAdvisor.get_quick_cot_summary()
                        elif clean_cmd in ["/analysis360", "/360", "/smc"]:
                            reply_text = DowAIAdvisor.get_quick_360_summary()
                        else:
                            # Natural language advisor reasoning query
                            reply_text = DowAIAdvisor.answer_question(text)

                        # Send reply back to user/chat
                        if reply_text:
                            dispatch_to_telegram_raw(bot_token, chat_id, reply_text)
                            _us30_interactive_bot_stats["queries_answered_total"] += 1
                            _us30_interactive_bot_stats["last_query"] = text
                            _us30_interactive_bot_stats["last_response"] = reply_text[:120]

        except urllib.error.URLError as e:
            _us30_interactive_bot_stats["last_error"] = f"URLError: {e.reason}"
            time.sleep(5)
        except Exception as e:
            _us30_interactive_bot_stats["last_error"] = str(e)
            time.sleep(5)

def prewarm_signals_in_background():
    time.sleep(1)
    for tf in ["1h", "15m", "5m", "30m", "4h", "1d"]:
        try:
            dow_composite_signal(tf)
        except Exception:
            pass

@app.get("/api/us30/supreme-arbiter")
def get_supreme_arbiter_status():
    return _unavailable_module(
        "supreme_arbiter",
        "اتصالات واقعی NinjaTrader/ATAS/Quantower/Bookmap متصل نیستند؛ داور نهادی تا زمان اتصال دادهٔ واقعی، معامله‌ای تأیید نمی‌کند.",
    )

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
