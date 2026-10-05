#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
aseman_resources.py — US30 adaptation of the useful institutional resources
extracted from the ASEMAN crypto project.

What was extracted/adapted:
1) Fast multi-source fetching pattern (fastfetch.py copied beside this file)
2) Macro Shield + US economic calendar + leading indicators
3) News Circuit Breaker pattern, rewritten for Dow/US equity headlines
4) Kelly/Risk engine, adapted from ASEMAN's calculator
5) Options analytics, adapted from Deribit/BTC concept to DIA/SPY Yahoo option chains
6) Alpha matrix concept, adapted from crypto leaders to US equity/index proxies
7) Golden filters concept, adapted from crypto derivatives/on-chain to US30 macro/flow filters
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

try:
    import yfinance as yf
except Exception:  # pragma: no cover
    yf = None

try:
    from fastfetch import fetch_many_json, gather, get_json
except Exception:  # pragma: no cover
    fetch_many_json = None
    gather = None
    get_json = None

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122 Safari/537.36"}
APP_DIR = Path(__file__).resolve().parent
TEH = ZoneInfo("Asia/Tehran")
NY = ZoneInfo("America/New_York")


def _clean(v: Any) -> Any:
    if v is None:
        return None
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating,)):
        f = float(v)
        return None if not np.isfinite(f) else round(f, 6)
    if isinstance(v, float):
        return None if not np.isfinite(v) else round(v, 6)
    if isinstance(v, (np.bool_, bool)):
        return bool(v)
    if isinstance(v, (pd.Timestamp, datetime)):
        return v.isoformat()
    if isinstance(v, np.ndarray):
        return [_clean(x) for x in v.tolist()]
    if isinstance(v, dict):
        return {str(k): _clean(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_clean(x) for x in v]
    return v


def _pct(new: float, old: float) -> float:
    return ((new - old) / old * 100.0) if old else 0.0


class AsemanMacroShieldUS30:
    """US macro shield adapted from ASEMAN EconomicCalendarEngine."""

    _cached_leading: Optional[Dict[str, Any]] = None
    _last_leading_time: float = 0

    # Static ASEMAN-style macro schedule, rewritten for US30 equity-index impact.
    MACRO_EVENTS: List[Dict[str, Any]] = [
        {
            "name": "US Non-Farm Payrolls & Unemployment — گزارش اشتغال NFP و نرخ بیکاری آمریکا",
            "code": "NFP",
            "impact": "CRITICAL_MAX",
            "impact_fa": "بسیار بالا / بحرانی",
            "volatility_fa": "نوسان شدید داوجونز، DXY و اوراق",
            "impact_color": "#ff3366",
            "date_utc": "2026-10-02 12:30:00",
            "date_tehran": "جمعه ۱۰ مهر ۱۴۰۵ — ساعت ۱۶:۰۰ به وقت تهران 🇮🇷",
            "epoch": 1790944200,
            "forecast": "165K",
            "previous": "142K",
            "forecast_context": "تعادل در اشتغال‌زایی و سناریوی فرود نرم؛ برای سهام صنعتی معمولاً سازنده است.",
            "us30_prediction": {
                "summary": "عدد متعادل/کمی ضعیف‌تر = کاهش فشار نرخ بهره و حمایت از داوجونز 🟢 | عدد خیلی داغ = ترس از نرخ بهره بالا و فشار فروش 🔴",
                "up_scenario": "NFP نزدیک یا کمی پایین‌تر از اجماع، همراه با بیکاری کنترل‌شده: کاهش بازده اوراق و رشد US30.",
                "down_scenario": "NFP بسیار بالاتر از اجماع: تقویت دلار/بازده و فشار روی سهام صنعتی.",
                "expected_dir": "صعودی مشروط به فرود نرم",
                "expected_color": "#00e676",
            },
            "reaction_inline": {
                "us30": {"arrow": "⬆️", "dir": "صعودی مشروط", "color": "#00e676", "desc": "فرود نرم و افت فشار نرخ بهره"},
                "dxy": {"arrow": "⬇️", "dir": "تضعیف دلار", "color": "#ff3366"},
                "us10y": {"arrow": "⬇️", "dir": "افت بازده", "color": "#ff3366"},
            },
            "reaction_higher": {
                "us30": {"arrow": "⬇️", "dir": "فشار فروش", "color": "#ff3366"},
                "dxy": {"arrow": "⬆️", "dir": "تقویت دلار", "color": "#00e676"},
                "us10y": {"arrow": "⬆️", "dir": "جهش بازده", "color": "#00e676"},
            },
            "reaction_lower": {
                "us30": {"arrow": "⬆️", "dir": "رالی نرخ بهره", "color": "#00e676"},
                "dxy": {"arrow": "⬇️", "dir": "افت دلار", "color": "#ff3366"},
                "us10y": {"arrow": "⬇️", "dir": "افت بازده", "color": "#ff3366"},
            },
        },
        {
            "name": "US CPI Inflation MoM/YoY — شاخص تورم مصرف‌کننده آمریکا",
            "code": "CPI",
            "impact": "CRITICAL_MAX",
            "impact_fa": "بسیار بالا / بحرانی",
            "volatility_fa": "نوسان بسیار شدید US30؛ ریسک شکار دوطرفه استاپ‌ها",
            "impact_color": "#ff3366",
            "date_utc": "2026-10-14 12:30:00",
            "date_tehran": "چهارشنبه ۲۲ مهر ۱۴۰۵ — ساعت ۱۶:۰۰ به وقت تهران 🇮🇷",
            "epoch": 1791981000,
            "forecast": "2.4%",
            "previous": "2.5%",
            "forecast_context": "مهار تورم، کاهش فشار فدرال‌رزرو و پشتیبانی از سهام داوجونز.",
            "us30_prediction": {
                "summary": "CPI کمتر/مطابق انتظار = رالی سهام و افت بازده 🟢 | CPI بالاتر = شوک نزولی US30 🔴",
                "up_scenario": "تورم کمتر از ۲.۴٪ یا مطابق انتظار: کاهش DXY/US10Y و احتمال رشد داوجونز.",
                "down_scenario": "تورم بالای ۲.۵٪: ترس از نرخ بهره بالا و فشار فروش روی شاخص‌های سهام.",
                "expected_dir": "صعودی اگر تورم کنترل‌شده بماند",
                "expected_color": "#00e676",
            },
            "reaction_inline": {
                "us30": {"arrow": "⬆️", "dir": "رالی سهام", "color": "#00e676", "desc": "کاهش انتظارات تورمی"},
                "dxy": {"arrow": "⬇️", "dir": "افت دلار", "color": "#ff3366"},
                "us10y": {"arrow": "⬇️", "dir": "افت بازده", "color": "#ff3366"},
            },
            "reaction_higher": {
                "us30": {"arrow": "⬇️", "dir": "ریزش/اصلاح", "color": "#ff3366"},
                "dxy": {"arrow": "⬆️", "dir": "جهش دلار", "color": "#00e676"},
                "us10y": {"arrow": "⬆️", "dir": "جهش بازده", "color": "#00e676"},
            },
            "reaction_lower": {
                "us30": {"arrow": "⬆️", "dir": "رالی قوی", "color": "#00e676"},
                "dxy": {"arrow": "⬇️", "dir": "افت دلار", "color": "#ff3366"},
                "us10y": {"arrow": "⬇️", "dir": "افت بازده", "color": "#ff3366"},
            },
        },
        {
            "name": "US GDP Annualized QoQ — تولید ناخالص داخلی سالانه آمریکا",
            "code": "GDP",
            "impact": "HIGH",
            "impact_fa": "بالا",
            "volatility_fa": "نوسان بالا اما معمولاً کمتر از CPI/FOMC",
            "impact_color": "#ff9800",
            "date_utc": "2026-10-29 12:30:00",
            "date_tehran": "پنجشنبه ۷ آبان ۱۴۰۵ — ساعت ۱۶:۰۰ به وقت تهران 🇮🇷",
            "epoch": 1793277000,
            "forecast": "2.8%",
            "previous": "3.0%",
            "forecast_context": "رشد سالم اقتصاد آمریکا؛ برای سهام صنعتی داوجونز مثبت است اگر تورم‌زا نباشد.",
            "us30_prediction": {
                "summary": "رشد متعادل = حمایت از داوجونز 🟢 | افت شدید رشد = ترس رکود 🔴 | رشد بیش از حد داغ = فشار بازده اوراق",
                "up_scenario": "GDP در محدوده ۲.۶٪ تا ۲.۹٪: تایید اقتصاد سالم و پشتیبانی از US30.",
                "down_scenario": "GDP زیر ۲٪ یا بسیار بالاتر از انتظار: ریسک رکود یا ریسک نرخ بهره.",
                "expected_dir": "صعودی ارگانیک",
                "expected_color": "#00e676",
            },
        },
        {
            "name": "US Core PCE Price Index — تورم هسته PCE آمریکا",
            "code": "PCE",
            "impact": "HIGH",
            "impact_fa": "بالا",
            "volatility_fa": "نوسان بالا برای US30 و بازده اوراق",
            "impact_color": "#ff9800",
            "date_utc": "2026-10-30 12:30:00",
            "date_tehran": "جمعه ۸ آبان ۱۴۰۵ — ساعت ۱۶:۰۰ به وقت تهران 🇮🇷",
            "epoch": 1793363400,
            "forecast": "2.5%",
            "previous": "2.6%",
            "forecast_context": "سنجه محبوب فدرال‌رزرو؛ کاهش آن برای داوجونز حمایتی است.",
            "us30_prediction": {
                "summary": "PCE پایین‌تر = کاهش فشار نرخ بهره و رشد سهام 🟢 | PCE بالاتر = فشار فروش 🔴",
                "up_scenario": "PCE ≤ 2.5٪: سیگنال نرم‌تر برای Fed و رشد US30.",
                "down_scenario": "PCE بالاتر از ۲.۷٪: بازده بالا و فشار روی سهام.",
                "expected_dir": "صعودی مشروط",
                "expected_color": "#00e676",
            },
        },
        {
            "name": "FOMC Interest Rate Decision — تصمیم نرخ بهره فدرال‌رزرو",
            "code": "FOMC",
            "impact": "CRITICAL_MAX",
            "impact_fa": "فوق بحرانی / بالاترین اهمیت",
            "volatility_fa": "نوسان طوفانی، خطر دام کنفرانس پاول",
            "impact_color": "#ff3366",
            "date_utc": "2026-11-04 19:00:00",
            "date_tehran": "چهارشنبه ۱۴ آبان ۱۴۰۵ — ساعت ۲۲:۳۰ به وقت تهران 🇮🇷",
            "epoch": 1793818800,
            "forecast": "4.50%",
            "previous": "4.75%",
            "forecast_context": "کاهش نرخ بهره اگر همراه با لحن داویش باشد برای داوجونز شدیداً حمایتی است.",
            "us30_prediction": {
                "summary": "کاهش نرخ + لحن داویش = رالی US30 🟢 | لحن هاوکیش پاول = برگشت نزولی 🔴",
                "up_scenario": "کاهش نرخ و تایید ادامه مسیر تسهیل: رشد سهام صنعتی و شاخص داوجونز.",
                "down_scenario": "عدم کاهش یا سخنان هاوکیش: جهش DXY/US10Y و فشار فروش US30.",
                "expected_dir": "صعودی اما با ریسک دام خبری",
                "expected_color": "#ff9100",
            },
            "reaction_inline": {
                "us30": {"arrow": "⬆️", "dir": "رالی داویش", "color": "#00e676", "desc": "کاهش هزینه سرمایه"},
                "dxy": {"arrow": "⬇️", "dir": "افت دلار", "color": "#ff3366"},
                "us10y": {"arrow": "⬇️", "dir": "افت بازده", "color": "#ff3366"},
            },
            "reaction_higher": {
                "us30": {"arrow": "⬇️", "dir": "فشار فروش", "color": "#ff3366"},
                "dxy": {"arrow": "⬆️", "dir": "جهش دلار", "color": "#00e676"},
                "us10y": {"arrow": "⬆️", "dir": "جهش بازده", "color": "#00e676"},
            },
            "reaction_lower": {
                "us30": {"arrow": "⬆️", "dir": "رالی پرقدرت", "color": "#00e676"},
                "dxy": {"arrow": "⬇️", "dir": "افت دلار", "color": "#ff3366"},
                "us10y": {"arrow": "⬇️", "dir": "افت بازده", "color": "#ff3366"},
            },
        },
    ]

    @classmethod
    def fetch_live_leading_indicators(cls) -> Dict[str, Any]:
        now = time.time()
        if cls._cached_leading and (now - cls._last_leading_time < 25):
            return cls._cached_leading

        urls = {
            "us30_cash": "https://query1.finance.yahoo.com/v8/finance/chart/%5EDJI",
            "dow_etf": "https://query1.finance.yahoo.com/v8/finance/chart/DIA",
            "spx": "https://query1.finance.yahoo.com/v8/finance/chart/%5EGSPC",
            "ndx": "https://query1.finance.yahoo.com/v8/finance/chart/%5ENDX",
            "vix": "https://query1.finance.yahoo.com/v8/finance/chart/%5EVIX",
            "dxy": "https://query1.finance.yahoo.com/v8/finance/chart/DX-Y.NYB",
            "us10y": "https://query1.finance.yahoo.com/v8/finance/chart/%5ETNX",
            "gold": "https://query1.finance.yahoo.com/v8/finance/chart/GC=F",
            "oil": "https://query1.finance.yahoo.com/v8/finance/chart/CL=F",
        }

        def one(key: str, url: str):
            try:
                req = urllib.request.Request(url, headers=UA)
                with urllib.request.urlopen(req, timeout=4) as resp:
                    d = json.loads(resp.read().decode("utf-8", "replace"))
                m = d["chart"]["result"][0]["meta"]
                p = float(m.get("regularMarketPrice") or m.get("previousClose") or 0)
                prev = float(m.get("chartPreviousClose") or m.get("previousClose") or p)
                return key, {"price": round(p, 3 if key == "us10y" else 2), "chg": round(_pct(p, prev), 2)}
            except Exception as e:
                return key, {"price": None, "chg": None, "error": str(e)[:90]}

        if gather:
            raw = gather({k: (lambda kk=k, uu=u: one(kk, uu)) for k, u in urls.items()}, timeout=5.5)
            indicators = {}
            for _, pair in raw.items():
                if isinstance(pair, tuple) and len(pair) == 2:
                    indicators[pair[0]] = pair[1]
        else:
            indicators = dict(one(k, u) for k, u in urls.items())

        dxy = indicators.get("dxy", {}) or {}
        us10y = indicators.get("us10y", {}) or {}
        vix = indicators.get("vix", {}) or {}
        spx = indicators.get("spx", {}) or {}
        ndx = indicators.get("ndx", {}) or {}

        score = 0.0
        notes = []
        # For US30, stronger dollar/yields/VIX are usually headwinds.
        if (dxy.get("chg") or 0) > 0.25:
            score -= 18; notes.append("DXY در حال تقویت است؛ فشار منفی روی سهام.")
        elif (dxy.get("chg") or 0) < -0.25:
            score += 14; notes.append("DXY ضعیف شده؛ برای US30 حمایتی است.")
        if (us10y.get("chg") or 0) > 0.8:
            score -= 22; notes.append("بازده ۱۰ساله جهش دارد؛ ارزش‌گذاری سهام تحت فشار.")
        elif (us10y.get("chg") or 0) < -0.8:
            score += 18; notes.append("افت بازده اوراق به نفع داوجونز است.")
        if (vix.get("price") or 0) >= 22 or (vix.get("chg") or 0) > 8:
            score -= 24; notes.append("VIX بالا/جهشی است؛ ریسک‌گریزی بازار زیاد شده.")
        elif (vix.get("price") or 0) and (vix.get("price") or 0) < 16:
            score += 8; notes.append("VIX پایین است؛ پنجره ریسک‌پذیری بازتر است.")
        if (spx.get("chg") or 0) > 0 and (ndx.get("chg") or 0) > 0:
            score += 10; notes.append("SPX و NDX همسو مثبت‌اند؛ breadth بین‌شاخصی مناسب است.")
        elif (spx.get("chg") or 0) < 0 and (ndx.get("chg") or 0) < 0:
            score -= 10; notes.append("SPX و NDX همسو منفی‌اند؛ فشار بازار گسترده است.")

        score = float(np.clip(score, -100, 100))
        regime = "RISK_ON" if score >= 15 else "RISK_OFF" if score <= -15 else "NEUTRAL"
        regime_fa = "ریسک‌پذیر / مساعد رشد US30" if regime == "RISK_ON" else "ریسک‌گریز / فشار روی US30" if regime == "RISK_OFF" else "خنثی / نیازمند تایید تکنیکال"

        fedwatch = cls._fedwatch_proxy(us10y.get("price"))
        out = {
            "success": True,
            "indicators": indicators,
            "macro_score": round(score, 1),
            "regime": regime,
            "regime_fa": regime_fa,
            "notes": notes,
            "fedwatch_proxy": fedwatch,
            "updated_at": datetime.now(TEH).strftime("%Y-%m-%d %H:%M:%S"),
        }
        cls._cached_leading = out
        cls._last_leading_time = now
        return out

    @staticmethod
    def _fedwatch_proxy(us10y_price: Optional[float]) -> Dict[str, Any]:
        y = float(us10y_price or 4.5)
        if y < 4.0:
            cut, pause = 88, 12
        elif y < 4.5:
            cut, pause = 82, 18
        elif y < 5.0:
            cut, pause = 74, 26
        else:
            cut, pause = 64, 36
        return {
            "prob_cut_25": cut,
            "prob_pause": pause,
            "summary": f"پروکسی داخلی: {cut}٪ احتمال کاهش/تسهیل در برابر {pause}٪ مکث",
            "verdict_fa": "افت احتمال نرخ بهره برای داوجونز حمایتی است؛ جهش بازده اوراق هشدار فشار فروش است.",
        }

    @classmethod
    def get_macro_shield_status(cls) -> Dict[str, Any]:
        now_epoch = time.time()
        ordered = sorted(cls.MACRO_EVENTS, key=lambda x: x["epoch"])
        freeze_ev = None
        for ev in ordered:
            diff = ev["epoch"] - now_epoch
            if -1800 <= diff <= 2700:  # 45m before to 30m after
                freeze_ev = ev
                break
        upcoming = [e for e in ordered if (e["epoch"] + 1800) >= now_epoch]
        if freeze_ev:
            next_ev = freeze_ev
            time_diff = next_ev["epoch"] - now_epoch
        elif upcoming:
            next_ev = upcoming[0]
            time_diff = next_ev["epoch"] - now_epoch
        else:
            next_ev = ordered[-1]
            time_diff = 0

        hours = int(abs(time_diff) // 3600)
        minutes = int((abs(time_diff) % 3600) // 60)
        if freeze_ev:
            shield_state = "🛑 فیوز کلان فعال — TRADING FREEZE"
            shield_color = "RED"
            shield_action = f"برای US30 ورود لوریج‌دار متوقف شود؛ رویداد {next_ev['code']} در پنجره شکار نقدینگی است."
            is_frozen = True
            countdown = f"{minutes} دقیقه تا/از خبر"
        elif time_diff <= 21600:
            shield_state = "⚠️ منطقه ریسک بالا"
            shield_color = "YELLOW"
            shield_action = f"رویداد {next_ev['code']} تا {hours} ساعت آینده است؛ حجم را کاهش دهید و از ورود تهاجمی دوری کنید."
            is_frozen = False
            countdown = f"{hours} ساعت و {minutes} دقیقه"
        else:
            shield_state = "🟢 پنجره کلان باثبات"
            shield_color = "GREEN"
            shield_action = "مانع کلان فوری نداریم؛ تصمیم را با SMC و اردرفلو بگیرید."
            is_frozen = False
            countdown = f"{hours} ساعت و {minutes} دقیقه"

        return _clean({
            "success": True,
            "next_event": next_ev["name"],
            "event_code": next_ev["code"],
            "impact": next_ev["impact"],
            "impact_fa": next_ev.get("impact_fa"),
            "volatility_fa": next_ev.get("volatility_fa"),
            "date_utc": next_ev["date_utc"],
            "date_tehran": next_ev.get("date_tehran"),
            "forecast": next_ev.get("forecast"),
            "previous": next_ev.get("previous"),
            "forecast_context": next_ev.get("forecast_context"),
            "us30_prediction": next_ev.get("us30_prediction", {}),
            "reaction_inline": next_ev.get("reaction_inline", {}),
            "reaction_higher": next_ev.get("reaction_higher", {}),
            "reaction_lower": next_ev.get("reaction_lower", {}),
            "countdown_seconds": int(time_diff),
            "countdown_fmt": countdown,
            "shield_state": shield_state,
            "shield_color": shield_color,
            "shield_action": shield_action,
            "is_frozen": is_frozen,
            "freeze_window_desc": "۴۵ دقیقه قبل تا ۳۰ دقیقه بعد از اخبار کلان قرمز",
            "leading_indicators": cls.fetch_live_leading_indicators(),
            "all_events": ordered,
            "source": "extracted/adapted from ASEMAN EconomicCalendarEngine",
        })


class AsemanNewsCircuitBreakerUS30:
    """ASEMAN NewsCircuitBreaker pattern rewritten for US30/Yahoo Finance RSS."""

    _cached: Optional[Dict[str, Any]] = None
    _last_time: float = 0

    RSS_URLS = [
        "https://feeds.finance.yahoo.com/rss/2.0/headline?s=%5EDJI,DIA,SPY,QQQ&region=US&lang=en-US",
        "https://feeds.finance.yahoo.com/rss/2.0/headline?s=%5EGSPC,%5ENDX,%5EVIX&region=US&lang=en-US",
    ]
    BEAR = re.compile(r"\b(crash|selloff|sell-off|plunge|recession|inflation|hawkish|default|shutdown|tariff|war|slump|bear|downgrade|yields rise|rates higher)\b", re.I)
    BULL = re.compile(r"\b(rally|surge|record|soft landing|rate cut|dovish|beats|optimism|stimulus|cooling inflation|strong earnings|gain)\b", re.I)

    @classmethod
    def fetch_live_news(cls) -> Dict[str, Any]:
        now = time.time()
        if cls._cached and now - cls._last_time < 120:
            return cls._cached
        items: List[Dict[str, Any]] = []
        errors = []
        for url in cls.RSS_URLS:
            try:
                req = urllib.request.Request(url, headers=UA)
                with urllib.request.urlopen(req, timeout=5) as resp:
                    xml = resp.read()
                root = ET.fromstring(xml)
                for it in root.findall(".//item")[:12]:
                    title = (it.findtext("title") or "").strip()
                    link = (it.findtext("link") or "").strip()
                    pub = (it.findtext("pubDate") or "").strip()
                    if not title:
                        continue
                    txt = title.lower()
                    b = bool(cls.BEAR.search(txt))
                    u = bool(cls.BULL.search(txt))
                    if b and not u:
                        sentiment = "BEARISH_RISK"
                        score = 78
                    elif u and not b:
                        sentiment = "BULLISH_CATALYST"
                        score = 28
                    else:
                        sentiment = "NEUTRAL"
                        score = 50
                    items.append({"title": title, "url": link, "published": pub, "sentiment": sentiment, "panic_score": score})
            except Exception as e:
                errors.append(str(e)[:100])
        # de-duplicate
        seen = set(); dedup = []
        for x in items:
            k = x["title"].lower()
            if k not in seen:
                seen.add(k); dedup.append(x)
        items = dedup[:20]
        panic_count = sum(1 for it in items[:10] if it["sentiment"] == "BEARISH_RISK")
        bull_count = sum(1 for it in items[:10] if it["sentiment"] == "BULLISH_CATALYST")
        avg_score = round(sum(it["panic_score"] for it in items[:10]) / max(1, min(10, len(items))), 1) if items else 50.0
        if panic_count >= 3 or avg_score >= 72:
            status = "EMERGENCY_NEWS_RISK"
            title = "🛑 فیوز خبری US30 فعال"
            advice = "چند تیتر منفی/سیستمی هم‌زمان دیده شد؛ ورود جدید تا آرام شدن خبرها محدود شود."
            badge = "RED"; safe = False
        elif panic_count >= 1 or avg_score >= 60:
            status = "CAUTION_HIGH_VOLATILITY"
            title = "⚠️ هشدار نوسان خبری"
            advice = "خبرهای ریسک‌زا دیده می‌شود؛ سایز را کوچک‌تر و استاپ را قطعی کنید."
            badge = "YELLOW"; safe = True
        else:
            status = "NORMAL_CLEAR"
            title = "🟢 وضعیت خبری عادی"
            advice = "خبر سیستماتیک خطرناک در تیترهای اسکن‌شده دیده نشد."
            badge = "GREEN"; safe = True
        out = {
            "success": True,
            "circuit_status": status,
            "circuit_title": title,
            "circuit_advice": advice,
            "badge": badge,
            "safe_to_trade": safe,
            "panic_count": panic_count,
            "bull_count": bull_count,
            "news_count": len(items),
            "avg_panic_score": avg_score,
            "news_items": items,
            "errors": errors,
            "updated_at": datetime.now(TEH).strftime("%Y-%m-%d %H:%M:%S"),
            "source": "ASEMAN NewsCircuitBreaker pattern + Yahoo Finance RSS for US30",
        }
        cls._cached = out
        cls._last_time = now
        return _clean(out)


class AsemanOptionsUS30:
    """Options analytics concept adapted from ASEMAN OptionsEngine to DIA/SPY option chains."""

    _cache: Dict[str, Dict[str, Any]] = {}

    @classmethod
    def get_options_analytics(cls, symbol: str = "DIA") -> Dict[str, Any]:
        symbol = (symbol or "DIA").upper()
        now = time.time()
        key = symbol
        if key in cls._cache and now - cls._cache[key]["ts"] < 300:
            return cls._cache[key]["data"]
        if yf is None:
            return {"success": False, "error": "yfinance not installed", "symbol": symbol}
        try:
            t = yf.Ticker(symbol)
            expiries = list(t.options or [])
            if not expiries:
                raise RuntimeError("No option expirations returned")
            expiry = expiries[0]
            chain = t.option_chain(expiry)
            calls = chain.calls.copy()
            puts = chain.puts.copy()
            for df in (calls, puts):
                if "openInterest" not in df.columns:
                    df["openInterest"] = 0
                if "volume" not in df.columns:
                    df["volume"] = 0
                df["openInterest"] = pd.to_numeric(df["openInterest"], errors="coerce").fillna(0)
                df["strike"] = pd.to_numeric(df["strike"], errors="coerce")
            total_calls = float(calls["openInterest"].sum())
            total_puts = float(puts["openInterest"].sum())
            pcr = round(total_puts / max(1.0, total_calls), 2)
            strikes = sorted(set(calls["strike"].dropna().tolist()) | set(puts["strike"].dropna().tolist()))
            c_oi = calls.groupby("strike")["openInterest"].sum().to_dict()
            p_oi = puts.groupby("strike")["openInterest"].sum().to_dict()
            max_pain = None; min_loss = float("inf")
            for s in strikes:
                loss = 0.0
                for k, oi in c_oi.items():
                    if s > k: loss += (s - k) * oi
                for k, oi in p_oi.items():
                    if s < k: loss += (k - s) * oi
                if loss < min_loss:
                    min_loss = loss; max_pain = s
            call_walls = calls.sort_values("openInterest", ascending=False).head(5)[["strike", "openInterest"]].to_dict("records")
            put_walls = puts.sort_values("openInterest", ascending=False).head(5)[["strike", "openInterest"]].to_dict("records")
            if pcr < 0.7:
                sentiment, bias = "کال‌ها غالب‌اند؛ تمایل ریسک‌پذیر", "BULLISH"
            elif pcr <= 1.05:
                sentiment, bias = "اختیار خرید/فروش متعادل", "NEUTRAL"
            else:
                sentiment, bias = "پوت‌ها غالب‌اند؛ پوشش ریسک/احتیاط", "BEARISH"
            out = _clean({
                "success": True,
                "symbol": symbol,
                "expiry": expiry,
                "total_calls_oi": total_calls,
                "total_puts_oi": total_puts,
                "pcr_ratio": pcr,
                "pcr_sentiment": sentiment,
                "pcr_bias": bias,
                "max_pain_strike_raw": max_pain,
                "max_pain_us30_proxy": float(max_pain) * 100.0 if symbol == "DIA" and max_pain else max_pain,
                "top_call_walls": call_walls,
                "top_put_walls": put_walls,
                "source": f"Yahoo Finance option chain / {symbol}",
                "updated_at": datetime.now(TEH).strftime("%Y-%m-%d %H:%M:%S"),
            })
            cls._cache[key] = {"ts": now, "data": out}
            return out
        except Exception as e:
            return {"success": False, "symbol": symbol, "error": str(e)}


class AsemanAlphaMatrixUS30:
    """Alpha matrix concept adapted from crypto leaders to indices/sectors relevant to US30."""

    _cached: Optional[Dict[str, Any]] = None
    _last_time: float = 0
    TICKERS = {
        "DIA": "Dow ETF",
        "SPY": "S&P 500",
        "QQQ": "Nasdaq 100",
        "IWM": "Russell 2000",
        "XLF": "Financials",
        "XLI": "Industrials",
        "XLK": "Technology",
        "XLE": "Energy",
        "XLV": "Healthcare",
        "GLD": "Gold ETF",
        "UUP": "Dollar ETF",
        "TLT": "Long Bonds",
    }

    @classmethod
    def get_matrix(cls) -> Dict[str, Any]:
        now = time.time()
        if cls._cached and now - cls._last_time < 180:
            return cls._cached
        if yf is None:
            return {"success": False, "error": "yfinance not installed", "leaders": []}
        try:
            syms = list(cls.TICKERS.keys())
            hist = yf.download(syms, period="10d", interval="1d", group_by="ticker", progress=False, auto_adjust=True, threads=True)
            items = []
            dia_ret = 0.0
            closes: Dict[str, pd.Series] = {}
            for s in syms:
                try:
                    c = hist[s]["Close"].dropna() if isinstance(hist.columns, pd.MultiIndex) else hist["Close"].dropna()
                    closes[s] = c
                    if s == "DIA" and len(c) >= 2:
                        dia_ret = _pct(float(c.iloc[-1]), float(c.iloc[-2]))
                except Exception:
                    pass
            for s, c in closes.items():
                if len(c) < 2:
                    continue
                r1 = _pct(float(c.iloc[-1]), float(c.iloc[-2]))
                r5 = _pct(float(c.iloc[-1]), float(c.iloc[-min(6, len(c))])) if len(c) >= 3 else r1
                alpha = round(r1 - dia_ret, 2)
                status = "لیدر نسبت به داو" if alpha >= 0.35 else "همسو با داو" if alpha >= -0.35 else "ضعیف‌تر از داو"
                badge = "LEADER" if alpha >= 0.35 else "INLINE" if alpha >= -0.35 else "LAGGARD"
                items.append({
                    "symbol": s, "name": cls.TICKERS[s], "price": float(c.iloc[-1]),
                    "change_1d": round(r1, 2), "change_5d": round(r5, 2),
                    "alpha_vs_dia": alpha, "status": status, "badge": badge,
                })
            items.sort(key=lambda x: x["alpha_vs_dia"], reverse=True)
            out = _clean({
                "success": True,
                "benchmark": "DIA",
                "dia_change_1d": round(dia_ret, 2),
                "top_alpha": items[0] if items else None,
                "worst_alpha": items[-1] if items else None,
                "leaders": items,
                "updated_at": datetime.now(TEH).strftime("%Y-%m-%d %H:%M:%S"),
                "source": "ASEMAN Alpha Matrix concept adapted to US index/sector ETFs",
            })
            cls._cached = out; cls._last_time = now
            return out
        except Exception as e:
            return {"success": False, "error": str(e), "leaders": []}


class AsemanKellyRiskUS30:
    """Kelly and safe leverage calculator adapted from ASEMAN KellyRiskEngine."""

    @classmethod
    def calculate(
        cls,
        balance: float = 10_000.0,
        risk_pct: float = 1.0,
        entry_price: float = 50_000.0,
        stop_loss: float = 49_500.0,
        take_profit: float = 51_000.0,
        win_rate_pct: float = 55.0,
        direction: str = "LONG",
        point_value: float = 1.0,
    ) -> Dict[str, Any]:
        balance = max(10.0, float(balance))
        risk_pct = max(0.1, min(20.0, float(risk_pct)))
        entry = max(1e-8, float(entry_price))
        sl = max(1e-8, float(stop_loss))
        tp = max(1e-8, float(take_profit))
        point_value = max(0.0001, float(point_value))
        p = max(0.05, min(0.95, float(win_rate_pct) / 100.0))
        q = 1.0 - p
        dollar_risk = balance * (risk_pct / 100.0)
        sl_points = abs(entry - sl)
        tp_points = abs(tp - entry)
        sl_dist_pct = max(0.01, sl_points / entry * 100.0)
        tp_dist_pct = tp_points / entry * 100.0
        rr = round(tp_points / max(sl_points, 1e-9), 2)
        b = max(0.1, rr)
        contracts = dollar_risk / max(sl_points * point_value, 1e-9)
        dollar_reward = contracts * tp_points * point_value
        raw_safe_lev = 100.0 / (sl_dist_pct * 1.5)
        safe_leverage = round(min(50.0, max(1.0, raw_safe_lev)), 1)
        margin_required = round((contracts * entry * point_value) / safe_leverage, 2)
        kelly_full = (p * (b + 1.0) - 1.0) / b
        kelly_half = max(0.0, kelly_full / 2.0)
        ev = round((p * dollar_reward) - (q * dollar_risk), 2)
        if kelly_full <= 0:
            advice = "⛔ امید ریاضی این ستاپ منفی است؛ معیار کلی ورود را تایید نمی‌کند."
            status = "NEGATIVE_EV"; color = "RED"
        elif risk_pct > (kelly_half * 100.0) and kelly_half > 0:
            advice = f"⚠️ ریسک انتخابی بالاتر از Half-Kelly ({kelly_half*100:.1f}٪) است؛ حجم را کاهش دهید."
            status = "OVER_RISK"; color = "YELLOW"
        else:
            advice = f"✅ ریسک با معیار کلی سازگار است؛ EV تقریبی: ${ev:,.2f}."
            status = "OPTIMAL_RISK"; color = "GREEN"
        return _clean({
            "success": True,
            "balance": balance,
            "risk_pct": risk_pct,
            "entry_price": entry,
            "stop_loss": sl,
            "take_profit": tp,
            "direction": direction,
            "point_value": point_value,
            "dollar_risk": round(dollar_risk, 2),
            "dollar_reward": round(dollar_reward, 2),
            "sl_points": round(sl_points, 2),
            "tp_points": round(tp_points, 2),
            "sl_distance_pct": round(sl_dist_pct, 2),
            "tp_distance_pct": round(tp_dist_pct, 2),
            "risk_reward_ratio": rr,
            "rr_fmt": f"1 : {rr}",
            "contracts_or_units": round(contracts, 4),
            "notional_value": round(contracts * entry * point_value, 2),
            "safe_leverage": safe_leverage,
            "margin_required": margin_required,
            "win_rate_used": round(p * 100.0, 1),
            "kelly_full_pct": round(kelly_full * 100.0, 1),
            "kelly_half_pct": round(kelly_half * 100.0, 1),
            "expected_value_usd": ev,
            "advice": advice,
            "status": status,
            "badge_color": color,
        })


class AsemanGoldenFiltersUS30:
    """Golden-six concept adapted to US30: macro, volatility, breadth, flow, options, news."""

    @classmethod
    def evaluate(cls, analysis: Optional[Dict[str, Any]] = None, direction: str = "LONG") -> Dict[str, Any]:
        analysis = analysis or {}
        direction = (direction or "LONG").upper()
        macro = AsemanMacroShieldUS30.get_macro_shield_status()
        lead = macro.get("leading_indicators", {})
        inds = lead.get("indicators", {})
        news = AsemanNewsCircuitBreakerUS30.fetch_live_news()
        opt = AsemanOptionsUS30.get_options_analytics("DIA")
        flow = analysis.get("flow", {}) if isinstance(analysis, dict) else {}
        signal = analysis.get("signal", {}) if isinstance(analysis, dict) else {}

        def chg(k):
            try: return float((inds.get(k) or {}).get("chg") or 0)
            except Exception: return 0.0
        def px(k):
            try: return float((inds.get(k) or {}).get("price") or 0)
            except Exception: return 0.0

        filters = []
        pass_count = 0
        # 1 Macro shield
        f = not bool(macro.get("is_frozen"))
        pass_count += int(f)
        filters.append({
            "id": 1, "name": "Macro Shield", "name_fa": "فیوز اخبار کلان آمریکا",
            "passed": f, "status": "PASS" if f else "FAIL",
            "value_display": macro.get("shield_color"),
            "description": macro.get("shield_action"),
            "importance": "جلوگیری از ورود در پنجره شکار نقدینگی CPI/FOMC/NFP",
        })
        # 2 DXY/US10Y
        if direction == "LONG":
            f = chg("dxy") <= 0.25 and chg("us10y") <= 0.8
            desc = "دلار/بازده مزاحم جدی لانگ نیستند." if f else "تقویت دلار یا بازده اوراق علیه لانگ US30 است."
        else:
            f = chg("dxy") >= -0.35 or chg("us10y") >= -0.8
            desc = "دلار/بازده از سناریوی شورت حمایت نسبی می‌کنند." if f else "افت دلار و بازده می‌تواند شورت را فشرده کند."
        pass_count += int(f)
        filters.append({"id": 2, "name": "DXY + US10Y", "name_fa": "دلار و بازده اوراق", "passed": f, "status": "PASS" if f else "FAIL", "value_display": f"DXY {chg('dxy'):+.2f}% | US10Y {chg('us10y'):+.2f}%", "description": desc, "importance": "مهم‌ترین وتوی کلان برای شاخص‌های سهام"})
        # 3 VIX
        if direction == "LONG":
            f = px("vix") < 22 and chg("vix") < 8
            desc = "VIX در محدوده قابل قبول است." if f else "VIX بالا/جهشی؛ خطر ریسک‌گریزی و شدوهای تند."
        else:
            f = px("vix") >= 15 or chg("vix") > 0
            desc = "VIX برای شورت مانع نیست." if f else "VIX خیلی پایین می‌تواند شورت را کم‌کیفیت کند."
        pass_count += int(f)
        filters.append({"id": 3, "name": "VIX Volatility", "name_fa": "شاخص ترس VIX", "passed": f, "status": "PASS" if f else "FAIL", "value_display": f"VIX {px('vix'):.2f} ({chg('vix'):+.2f}%)", "description": desc, "importance": "کنترل رژیم نوسان و ریسک‌گریزی"})
        # 4 Breadth SPX/NDX
        if direction == "LONG":
            f = chg("spx") >= -0.2 and chg("ndx") >= -0.3
            desc = "SPX/NDX فشار گسترده علیه داو ندارند." if f else "فشار همگانی بازار، لانگ داو را تضعیف می‌کند."
        else:
            f = chg("spx") <= 0.25 or chg("ndx") <= 0.25
            desc = "breadth برای سناریوی شورت قابل قبول است." if f else "رالی گسترده بازار می‌تواند شورت را بسوزاند."
        pass_count += int(f)
        filters.append({"id": 4, "name": "Index Breadth", "name_fa": "همسویی SPX/NDX", "passed": f, "status": "PASS" if f else "FAIL", "value_display": f"SPX {chg('spx'):+.2f}% | NDX {chg('ndx'):+.2f}%", "description": desc, "importance": "جلوگیری از خلاف‌جهت رفتن با کل بازار"})
        # 5 Order flow from local analysis
        cmf = float(flow.get("cmf") or flow.get("cmf_last") or 0)
        cd = float(flow.get("cd_slope") or 0)
        if direction == "LONG":
            f = cmf >= -0.08 and cd >= -0.35
            desc = "جریان پول داخلی علیه لانگ نیست." if f else "CMF/CVD فروش نهادی را نشان می‌دهد."
        else:
            f = cmf <= 0.08 and cd <= 0.35
            desc = "جریان پول داخلی برای شورت مانع جدی نیست." if f else "جریان خرید، شورت را پرریسک می‌کند."
        pass_count += int(f)
        filters.append({"id": 5, "name": "Local Order Flow", "name_fa": "CMF/CVD داخلی", "passed": f, "status": "PASS" if f else "FAIL", "value_display": f"CMF {cmf:+.3f} | CD {cd:+.3f}", "description": desc, "importance": "راستی‌آزمایی سیگنال SMC با جریان پول"})
        # 6 News/options
        pcr = float(opt.get("pcr_ratio") or 1.0) if opt.get("success") else 1.0
        if direction == "LONG":
            f = news.get("safe_to_trade", True) and pcr <= 1.25
            desc = "خبر و آپشن مانع جدی برای لانگ نیست." if f else "ریسک خبری یا پوشش پوت بالا، لانگ را تضعیف می‌کند."
        else:
            f = news.get("badge") != "GREEN" or pcr >= 0.65
            desc = "خبر/آپشن برای شورت قابل قبول است." if f else "فضای خبری خیلی آرام و کال‌محور است."
        pass_count += int(f)
        filters.append({"id": 6, "name": "News + Options", "name_fa": "فیوز خبری و PCR آپشن", "passed": f, "status": "PASS" if f else "FAIL", "value_display": f"News {news.get('badge')} | PCR {pcr:.2f}", "description": desc, "importance": "ترکیب سنتیمنت خبری با پوشش اختیار معامله"})

        quality = pass_count / 6.0
        if quality >= 0.84:
            verdict = "A+ — شش‌فیلتر آسمان برای US30 ستاپ را تایید می‌کند"
            color = "GREEN"
        elif quality >= 0.67:
            verdict = "A/B — شرایط قابل قبول اما با یک یا دو هشدار"
            color = "YELLOW"
        else:
            verdict = "C/RISK — فیلترهای نهادی کافی پاس نشده‌اند"
            color = "RED"
        return _clean({
            "success": True,
            "asset": "US30",
            "direction": direction,
            "pass_count": pass_count,
            "total": 6,
            "quality_score": round(quality * 100, 1),
            "verdict": verdict,
            "badge_color": color,
            "filters": filters,
            "source": "ASEMAN GoldenSix concept adapted to US30",
        })


class AsemanMacroJournalUS30:
    """Small benchmark journal adapted from ASEMAN macro_journal concept."""

    JOURNAL = [
        {
            "id": "US30-MACRO-20261014-CPI",
            "event_code": "CPI",
            "event_name": "US CPI MoM/YoY — شاخص تورم مصرف‌کننده آمریکا",
            "date_tehran": "چهارشنبه ۲۲ مهر ۱۴۰۵ — ساعت ۱۶:۰۰ به وقت تهران 🇮🇷",
            "consensus": "2.4% (کاهش از ۲.۵٪ قبلی)",
            "ai_prediction": "تورم کمتر/مطابق انتظار = رالی US30؛ تورم بالاتر از انتظار = فشار فروش",
            "bias_direction": "صعودی مشروط به کنترل تورم",
            "expected_color": "#ff9100",
            "actual_released": "در انتظار انتشار رسمی",
            "accuracy_status": "PENDING_LIVE",
            "audit_notes": "این قالب از ژورنال کلان ASEMAN استخراج و برای US30 بازنویسی شده است.",
        },
        {
            "id": "US30-MACRO-20261029-GDP",
            "event_code": "GDP",
            "event_name": "US GDP Annualized QoQ — تولید ناخالص داخلی آمریکا",
            "date_tehran": "پنجشنبه ۷ آبان ۱۴۰۵ — ساعت ۱۶:۰۰ به وقت تهران 🇮🇷",
            "consensus": "2.8%",
            "ai_prediction": "رشد متعادل = داوجونز سالم؛ افت شدید = ترس رکود؛ رشد بیش از حد داغ = فشار نرخ بهره",
            "bias_direction": "صعودی ارگانیک",
            "expected_color": "#00e676",
            "actual_released": "در انتظار انتشار رسمی",
            "accuracy_status": "PENDING_LIVE",
            "audit_notes": "سناریوهای کلان برای بازار سهام صنعتی بازنویسی شده‌اند.",
        },
        {
            "id": "US30-MACRO-20261104-FOMC",
            "event_code": "FOMC",
            "event_name": "FOMC Interest Rate Decision — تصمیم نرخ بهره فدرال‌رزرو",
            "date_tehran": "چهارشنبه ۱۴ آبان ۱۴۰۵ — ساعت ۲۲:۳۰ به وقت تهران 🇮🇷",
            "consensus": "4.50%",
            "ai_prediction": "کاهش نرخ + لحن داویش = رالی US30؛ لحن هاوکیش پاول = دام نزولی بعد از پامپ اولیه",
            "bias_direction": "صعودی با ریسک دام کنفرانس",
            "expected_color": "#ff9100",
            "actual_released": "در انتظار انتشار رسمی",
            "accuracy_status": "PENDING_LIVE",
            "audit_notes": "از Macro Shield آسمان استخراج و برای Dow/US30 تطبیق داده شد.",
        },
    ]

    @classmethod
    def get_journal(cls) -> Dict[str, Any]:
        verified = [x for x in cls.JOURNAL if str(x.get("accuracy_status", "")).startswith("VERIFIED")]
        pending = [x for x in cls.JOURNAL if str(x.get("accuracy_status", "")).startswith("PENDING")]
        return {
            "success": True,
            "records": cls.JOURNAL,
            "total": len(cls.JOURNAL),
            "verified_count": len(verified),
            "pending_count": len(pending),
            "source": "ASEMAN macro_journal pattern adapted to US30",
        }


def build_aseman_suite(analysis: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """One-call suite used by /api/analyze and /api/aseman/suite."""
    sig = (analysis or {}).get("signal", {}) if isinstance(analysis, dict) else {}
    direction = "LONG" if int(sig.get("direction", 0) or 0) >= 0 else "SHORT"
    plan = sig.get("plan", {}) if isinstance(sig, dict) else {}
    kelly = None
    if plan and plan.get("entry") and plan.get("stop") and plan.get("tp1"):
        kelly = AsemanKellyRiskUS30.calculate(
            balance=float((analysis or {}).get("position_sizing", {}).get("equity", 10000) or 10000),
            risk_pct=float((analysis or {}).get("position_sizing", {}).get("risk_pct", 1.0) or 1.0),
            entry_price=float(plan.get("entry")),
            stop_loss=float(plan.get("stop")),
            take_profit=float(plan.get("tp1")),
            win_rate_pct=max(50.0, float(sig.get("confidence") or 55.0)),
            direction=direction,
        )
    return _clean({
        "success": True,
        "macro_shield": AsemanMacroShieldUS30.get_macro_shield_status(),
        "news_circuit": AsemanNewsCircuitBreakerUS30.fetch_live_news(),
        "options": AsemanOptionsUS30.get_options_analytics("DIA"),
        "alpha_matrix": AsemanAlphaMatrixUS30.get_matrix(),
        "golden_filters": AsemanGoldenFiltersUS30.evaluate(analysis, direction),
        "kelly_risk": kelly,
        "macro_journal": AsemanMacroJournalUS30.get_journal(),
        "extracted_modules": [
            "fastfetch parallel cache",
            "EconomicCalendarEngine → US30 Macro Shield",
            "NewsCircuitBreaker → US30 headline risk",
            "OptionsEngine concept → DIA/SPY options analytics",
            "AlphaCorrelationEngine concept → US index/sector alpha matrix",
            "KellyRiskEngine → US30 risk calculator",
            "GoldenSixCoreEngine concept → US30 six institutional filters",
            "macro_journal → US30 macro benchmark journal",
        ],
    })
