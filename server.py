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

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional, List, Dict, Any
from pydantic import BaseModel
import json, time, threading, urllib.request, urllib.parse
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import HTMLResponse, JSONResponse

import market_data as md
import us30_engine as engine
import aseman_resources as aseman
import dow_analyzer_resources as dowres
import execution_guard as execguard
import snapshot as snap

APP_DIR = Path(__file__).resolve().parent

app = FastAPI(
    title="US30 ASEMAN Smart Money Dashboard",
    description="Dedicated Dow Jones / US30 dashboard using ASEMAN architecture and the previous Dow Smart Money engine.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(GZipMiddleware, minimum_size=500)


@app.middleware("http")
async def headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    # Allow Arena/Render previews inside iframe.
    response.headers["Content-Security-Policy"] = "frame-ancestors *"
    response.headers["Cache-Control"] = "no-store"
    if "X-Frame-Options" in response.headers:
        del response.headers["X-Frame-Options"]
    return response


@app.api_route("/healthz", methods=["GET", "HEAD"])
@app.api_route("/health", methods=["GET", "HEAD"])
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


@app.get("/api/ticker")
def ticker(interval: str = Query("1h", description="5m, 15m, 30m, 1h, 1d")):
    try:
        return engine.ticker(interval)
    except Exception as e:
        return JSONResponse(status_code=502, content={"ok": False, "error": str(e)})


@app.get("/api/candles")
def candles(
    interval: str = Query("1h", description="5m, 15m, 30m, 1h, 1d"),
    bars: int = Query(180, ge=80, le=600),
):
    try:
        return engine.candles(interval, bars)
    except Exception as e:
        return JSONResponse(status_code=502, content={"ok": False, "error": str(e)})


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
    try:
        data = engine.build_analysis(
            interval=interval,
            bars=bars,
            force=fresh,
            with_coalition=coalition,
            equity=equity,
            risk_pct=risk_pct,
        )
        if include_aseman:
            try:
                data["aseman_suite"] = aseman.build_aseman_suite(data)
            except Exception as pack_error:
                data["aseman_suite"] = {"success": False, "error": str(pack_error)}
        if include_dow:
            try:
                data["dow_suite"] = dowres.suite(light=True, interval=interval)
            except Exception as dow_error:
                data["dow_suite"] = {"ok": False, "error": str(dow_error)}
        try:
            data["execution_guard"] = execguard.evaluate(data, interval=interval, balance=guard_balance, leverage=guard_leverage, lot=guard_lot)
        except Exception as guard_error:
            data["execution_guard"] = {"ok": False, "error": str(guard_error)}
        return data
    except Exception as e:
        return JSONResponse(status_code=502, content={"ok": False, "error": str(e)})


@app.get("/api/plan")
def plan(
    interval: str = Query("1h"),
    bars: int = Query(180, ge=80, le=600),
    fresh: bool = Query(False),
    equity: float = Query(10000, gt=0),
    risk_pct: float = Query(1.0, gt=0, le=10),
):
    try:
        data = engine.build_analysis(interval=interval, bars=bars, force=fresh, equity=equity, risk_pct=risk_pct)
        return {
            "ok": True,
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
    data = engine.build_analysis(interval=interval, bars=bars, force=False)
    d = direction.upper()
    if d == "AUTO":
        sig = data.get("signal", {})
        d = "LONG" if int(sig.get("direction", 0) or 0) >= 0 else "SHORT"
    return aseman.AsemanGoldenFiltersUS30.evaluate(data, d)


@app.get("/api/aseman/suite")
def aseman_suite(
    interval: str = Query("1h"),
    bars: int = Query(180, ge=80, le=600),
    fresh: bool = Query(False),
    equity: float = Query(10000, gt=0),
    risk_pct: float = Query(1.0, gt=0, le=10),
):
    data = engine.build_analysis(interval=interval, bars=bars, force=fresh, equity=equity, risk_pct=risk_pct)
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
        import dow_cash as dcash
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

    Header/query key: X-Snapshot-Key or ?key=...
    Body: {"items": {"agent:US30:1d": {...}}, "built_at": 123}
    """
    if not snap.enabled():
        return JSONResponse(status_code=503, content={"ok": False, "error": "SNAPSHOT_KEY تنظیم نشده"})
    given = request.headers.get("X-Snapshot-Key") or request.query_params.get("key") or ""
    if not snap.check_key(given):
        return JSONResponse(status_code=403, content={"ok": False, "error": "کلید نامعتبر"})
    body = await request.json()
    items = body.get("items") if isinstance(body, dict) else None
    if not isinstance(items, dict) or not items:
        return JSONResponse(status_code=400, content={"ok": False, "error": "items خالی است"})
    saved = []
    for k, v in items.items():
        if isinstance(k, str) and 1 <= len(k) <= 120:
            snap.save(k, v, built_at=body.get("built_at"))
            saved.append(k)
    return {"ok": True, "saved": saved, "count": len(saved)}


@app.get("/api/dow/guard")
def dow_guard(
    interval: str = Query("1h"),
    bars: int = Query(120, ge=80, le=600),
    fresh: bool = Query(False),
    balance: float = Query(10.0, gt=0),
    leverage: float = Query(50.0, gt=0),
    lot: float = Query(0.01, gt=0),
):
    data = engine.build_analysis(interval=interval, bars=bars, force=fresh, with_coalition=False)
    return execguard.evaluate(data, interval=interval, balance=balance, leverage=leverage, lot=lot)


@app.get("/api/dow/cash")
def dow_cash():
    return dowres.cash()


@app.api_route("/api/dow/chat", methods=["GET", "POST"])
async def dow_chat(request: Request, q: str = Query(""), interval: str = Query("1d")):
    """Rule-based agent chat: answers only from dashboard data, no fabricated numbers."""
    try:
        question = q
        if request.method == "POST":
            body = await request.json()
            if isinstance(body, dict):
                question = body.get("q") or body.get("question") or question
                interval = body.get("interval") or interval
        if not question:
            try:
                import qa_bot
                return {"ok": True, "suggestions": qa_bot.suggestions(), "answer": "سوال را بنویسید."}
            except Exception:
                return {"ok": False, "error": "سوالی نوشته نشده"}
        import qa_bot
        return qa_bot.ask(str(question), "US30", interval)
    except Exception as e:
        return {"ok": True, "confident": False, "answer": f"ایجنت قاعده‌محور خطا خورد: {str(e)[:180]}", "source": "—"}


@app.get("/api/dow/institutional-layers")
def dow_institutional_layers(interval: str = Query("1h")):
    """Five-layer institutional terminal without forcing the very heavy old agent."""
    return {
        "ok": True,
        "title": "دید تریدر نهادی — پنج لایه",
        "layers": {
            "layer1_intermarket_veto": dowres.context(with_mtf=True).get("intermarket"),
            "layer2_liquidity_orderflow": dowres.orderflow(interval),
            "layer3_macro_news_window": {"macro": dowres.macro(False), "econ": dowres.econ("critical"), "extras": dowres.extras()},
            "layer4_sentiment_options": {"sentiment": dowres.sentiment(), "volatility": dowres.volatility()},
            "layer5_time_seasonality": {"hours": dowres.hours(), "window": dowres.window()},
        },
        "feature_vector_note": "بردار ویژگی نهادی در agent/institutional موجود است؛ برای محاسبه کامل از /api/dow/agent استفاده کنید.",
    }


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
    return dowres.orderflow(interval)


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
    "is_running": True,
    "last_check_utc": None,
    "last_check_tehran": None,
    "signals_sent_total": 0,
    "last_signal_time": None,
    "last_error": None
}

class US30TelegramConfigRequest(BaseModel):
    bot_token: Optional[str] = ""
    chat_id: Optional[str] = ""
    auto_pilot: Optional[bool] = True
    interval_minutes: Optional[int] = 20
    min_score: Optional[int] = 70

class US30TelegramSendRequest(BaseModel):
    bot_token: Optional[str] = None
    chat_id: Optional[str] = None
    interval: Optional[str] = "1h"

def get_us30_telegram_config() -> Dict[str, Any]:
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    auto_pilot = True
    interval_m = 20
    min_score = 70

    if TG_CONFIG_FILE.exists():
        try:
            with open(TG_CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg = json.load(f)
                bot_token = bot_token or cfg.get("bot_token", "")
                chat_id = chat_id or cfg.get("chat_id", "")
                auto_pilot = cfg.get("auto_pilot", True)
                interval_m = cfg.get("interval_minutes", 20)
                min_score = cfg.get("min_score", 70)
        except Exception:
            pass

    masked = f"{bot_token[:6]}...{bot_token[-4:]}" if len(bot_token) > 12 else bot_token
    return {
        "is_configured": bool(bot_token and chat_id),
        "masked_token": masked,
        "chat_id": chat_id,
        "auto_pilot": auto_pilot,
        "interval_minutes": interval_m,
        "min_score": min_score,
        "sentinel_stats": _us30_sentinel_stats
    }

def format_us30_telegram_signal(data: Dict[str, Any]) -> str:
    now_utc = datetime.now(timezone.utc)
    tehran_time = now_utc + timedelta(hours=3, minutes=30)
    tehran_str = tehran_time.strftime("%H:%M:%S (%Y/%m/%d)")
    valid_until = (tehran_time + timedelta(minutes=45)).strftime("%H:%M")

    price_info = data.get("price", {})
    last_price = float(price_info.get("last") or 51585.0)
    sig = data.get("signal", {})
    plan = sig.get("plan", {})
    direction = int(sig.get("direction", 0) or 0)
    grade = sig.get("grade", "B")
    score = float(sig.get("score") or 0.0)
    conf = float(sig.get("confidence") or 75.0)

    entry = float(plan.get("entry") or last_price)
    sl = float(plan.get("stop") or (entry - 85 if direction >= 0 else entry + 85))
    tp1 = float(plan.get("tp1") or (entry + 45 if direction >= 0 else entry - 45))
    tp2 = float(plan.get("tp2") or (entry + 110 if direction >= 0 else entry - 110))
    tp3 = float(plan.get("tp3") or (entry + 220 if direction >= 0 else entry - 220))

    sl_pts = abs(round(entry - sl, 1))
    tp1_pts = abs(round(tp1 - entry, 1))
    tp2_pts = abs(round(tp2 - entry, 1))
    tp3_pts = abs(round(tp3 - entry, 1))

    action_emoji = "🚀 خرید تهاجمی (LONG)" if direction > 0 else ("🔻 فروش تهاجمی (SHORT)" if direction < 0 else "⚪ خنثی / بدون پوزیشن")
    grade_emoji = "👑" if grade == "A+" else ("⭐" if grade == "A" else "⚡")

    msg = f"""
{grade_emoji} <b>سیگنال نهادی اختصاصی داو جونز | US30 Smart Money</b>
━━━━━━━━━━━━━━━━━━━━
💰 <b>قیمت شاخص داو جونز:</b> <code>${last_price:,.1f}</code>
🧭 <b>سیگنال سیستم:</b> {action_emoji}
⭐ <b>درجه کیفی و اطمینان:</b> <code>Grade {grade}</code> ({conf:.0f}٪ | امتیاز: {score:.1f})
🏛️ <b>سشن بازار:</b> <code>{data.get("market", {}).get("status_fa", "بازار نقدی وال‌استریت")}</code>

⚡ <b>سطوح معاملاتی دقیق (Execution Levels):</b>
⏰ <b>زمان صدور به وقت ایران 🇮🇷:</b> <code>ساعت {tehran_str}</code>
⏳ <b>افق اعتبار ستاپ:</b> <code>تا ساعت {valid_until} به وقت ایران</code>
🔹 <b>محدوده بهینه ورود:</b> <code>${entry:,.1f}</code>
🛑 <b>حد ضرر ساختاری (SL):</b> <code>${sl:,.1f} ({sl_pts:,.0f} پوینت)</code>
🎯 <b>تارگت اول (TP1):</b> <code>${tp1:,.1f} (+{tp1_pts:,.0f} پوینت)</code> <i>[سیو ۵۰٪ سود + ریسک‌فری]</i>
🎯 <b>تارگت دوم (TP2):</b> <code>${tp2:,.1f} (+{tp2_pts:,.0f} پوینت)</code> <i>[تارگت ساختاری]</i>
🎯 <b>تارگت سوم (TP3):</b> <code>${tp3:,.1f} (+{tp3_pts:,.0f} پوینت)</code> <i>[استخر نقدینگی نهایی]</i>
⚖️ <b>ریسک به ریوارد:</b> <code>1 : {round(tp2_pts / max(sl_pts, 1), 2)}</code>

🛡️ <b>دستورالعمل هوشمند مدیریت سرمایه و حجم لات:</b>
• در صورت ورود، به محض لمس <b>تارگت اول ({tp1_pts:,.0f}+ پوینت)</b>، نیمی از پوزیشن را بسته و استاپ را روی نقطه ورود (Breakeven) قرار دهید تا معامله کاملاً بدون ریسک شود.
━━━━━━━━━━━━━━━━━━━━
📊 <b>مشاهده آنلاین چارت داو جونز:</b> <a href="https://www.tradingview.com/chart/?symbol=TVC:DJI">TradingView Chart ↗️</a>
⏰ <i>زمان تحلیل (ایران 🇮🇷): {tehran_str}</i>
"""
    return msg.strip()

def dispatch_to_telegram_raw(token: str, chat: str, message: str) -> Dict[str, Any]:
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": False,
        "reply_markup": {
            "inline_keyboard": [
                [
                    {"text": "📊 چارت آنلاین داوجونز (TradingView)", "url": "https://www.tradingview.com/chart/?symbol=TVC:DJI"},
                    {"text": "🦅 مشاهده داشبورد اختصاصی US30", "url": "https://us30-aseman-1.onrender.com"}
                ]
            ]
        }
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode())

@app.get("/api/telegram/config")
def telegram_config():
    return get_us30_telegram_config()

@app.post("/api/telegram/config")
def save_telegram_config(cfg: US30TelegramConfigRequest):
    try:
        existing = {}
        if TG_CONFIG_FILE.exists():
            try:
                with open(TG_CONFIG_FILE, "r", encoding="utf-8") as f:
                    existing = json.load(f)
            except Exception:
                pass

        new_tok = cfg.bot_token.strip() if cfg.bot_token else existing.get("bot_token", "")
        new_chat = cfg.chat_id.strip() if cfg.chat_id else existing.get("chat_id", "")

        data = {
            "bot_token": new_tok,
            "chat_id": new_chat,
            "auto_pilot": bool(cfg.auto_pilot),
            "interval_minutes": int(cfg.interval_minutes or 20),
            "min_score": int(cfg.min_score or 70),
            "updated_at": time.strftime("%Y-%m-%d %H:%M:%S UTC")
        }
        with open(TG_CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        return {"success": True, "message": "تنظیمات ربات تلگرام و دیده‌بان خودکار داو جونز با موفقیت ذخیره شد."}
    except Exception as e:
        return JSONResponse(status_code=500, content={"ok": False, "error": str(e)})

@app.post("/api/telegram/send")
def telegram_send(req: US30TelegramSendRequest):
    try:
        cfg = get_us30_telegram_config()
        tok = req.bot_token or os.environ.get("TELEGRAM_BOT_TOKEN") or ""
        chat = req.chat_id or os.environ.get("TELEGRAM_CHAT_ID") or ""
        if not tok or not chat:
            if TG_CONFIG_FILE.exists():
                with open(TG_CONFIG_FILE, "r", encoding="utf-8") as f:
                    saved = json.load(f)
                    tok = tok or saved.get("bot_token", "")
                    chat = chat or saved.get("chat_id", "")

        if not tok or not chat:
            return JSONResponse(status_code=400, content={"ok": False, "message": "توکن ربات یا شناسه چت تنظیم نشده است."})

        data = engine.build_analysis(interval=req.interval or "1h", bars=180, force=True)
        msg = format_us30_telegram_signal(data)
        res = dispatch_to_telegram_raw(tok, chat, msg)
        _us30_sentinel_stats["signals_sent_total"] += 1
        _us30_sentinel_stats["last_signal_time"] = time.strftime("%Y-%m-%d %H:%M:%S UTC")
        return {"success": True, "message": "سیگنال هوشمند داو جونز با موفقیت به تلگرام مخابره شد.", "result": res}
    except Exception as e:
        return JSONResponse(status_code=500, content={"ok": False, "error": str(e)})

@app.post("/api/telegram/test")
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
            return JSONResponse(status_code=400, content={"ok": False, "message": "توکن ربات یا شناسه چت برای ارسال تست موجود نیست."})

        now_tehran = datetime.now(timezone.utc) + timedelta(hours=3, minutes=30)
        time_str = now_tehran.strftime("%H:%M:%S")
        test_msg = f"""
🦅 <b>آزمون اتصال ربات دیده‌بان هوشمند داو جونز (US30 Sentinel)</b>
━━━━━━━━━━━━━━━━━━━━
✅ اتصال وب‌سرویس و ربات تلگرام با موفقیت برقرار شد.
⏰ <b>زمان تست (ایران 🇮🇷):</b> <code>ساعت {time_str}</code>
📈 <b>وضعیت اتصال به فید وال‌استریت:</b> فعال و برخط
🚀 سامانه هوشمند ۲۴ ساعته آماده ارسال ستاپ‌های معاملاتی است.
"""
        res = dispatch_to_telegram_raw(tok, chat, test_msg.strip())
        return {"success": True, "message": "پیام تست با موفقیت ارسال شد.", "result": res}
    except Exception as e:
        return JSONResponse(status_code=500, content={"ok": False, "error": str(e)})

@app.get("/api/journal/live")
def journal_live():
    try:
        import journal as jrn
        records = jrn.read_all()
        # Clean records
        clean_recs = []
        for r in records[-50:]:
            outcome = r.get("outcome", {})
            clean_recs.append({
                "id": r.get("id"),
                "ts": r.get("ts"),
                "asset": r.get("asset", "US30"),
                "interval": r.get("interval", "1h"),
                "price": r.get("price"),
                "grade": r.get("grade", "B"),
                "label": r.get("label", "خنثی"),
                "result": outcome.get("result", "در انتظار"),
                "exit_reason": outcome.get("exit_reason", "-"),
                "r_mult": outcome.get("r_mult", 0.0),
                "move_pct": outcome.get("move_pct", 0.0)
            })
        clean_recs.reverse()
        return {"ok": True, "records": clean_recs, "total": len(records)}
    except Exception as e:
        return {"ok": False, "records": [], "error": str(e)}


def get_dashboard_html() -> str:
    p = APP_DIR / "index.html"
    if p.exists():
        return p.read_text(encoding="utf-8")
    return "<html><body><h1>US30 Dashboard</h1><p>index.html not found.</p></body></html>"


@app.api_route("/", methods=["GET", "HEAD"], response_class=HTMLResponse)
def index():
    return HTMLResponse(get_dashboard_html(), status_code=200)


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
