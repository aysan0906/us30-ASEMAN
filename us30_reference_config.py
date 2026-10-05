#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Canonical US30/Dow Jones data-source and broker settings.

This file records the user's 2026-10-01 reference notes as executable/static
configuration for the new Render dashboard.
"""

from __future__ import annotations

from datetime import time
from typing import Dict, Any

YAHOO_CHART_ENDPOINT = "https://query1.finance.yahoo.com/v8/finance/chart/{SYMBOL}"
YAHOO_REQUIRED_HEADERS = {"User-Agent": "Mozilla/5.0"}

YAHOO_INTERVAL_LIMITS = {
    "1m": "7d",
    "5m": "60d",
    "15m": "60d",
    "30m": "60d",
    "1h": "730d",
    "1d": "max",
}

US30_SYMBOL_ROLES = {
    "cash_live": {
        "symbol": "^DJI",
        "use": "قیمت لحظه‌ای/نمایشی وقتی بازار نقدی باز است",
        "observed_delay_min": 0.0,
        "trendo_diff_points_2026_09_23": -52,
    },
    "historical_candles": {
        "symbol": "DIA",
        "use": "کندل تاریخی و تحلیل؛ ضرب در ضریب نمایش یا فاکتور پویا",
        "display_scale": 100.0,
        "observed_delay_min": 0.2,
        "trendo_diff_points_2026_09_23": -116,
    },
    "closed_market_proxy": {
        "symbol": "YM=F",
        "use": "ساعات بسته بودن بورس: futures - live basis",
        "observed_delay_min": 10.0,
        "trendo_diff_points_2026_09_23": 409,
        "basis_formula": "cash_estimate = YM=F_now - (YM=F_at_overlap - ^DJI_at_overlap)",
        "warning": "basis ثابت نیست؛ در ۲۰ روز بین ۱۲ تا ۴۲۶ واحد نوسان کرده است.",
    },
}

INTERMARKET_MEASURED = {
    "DX-Y.NYB": {
        "key": "dxy",
        "name": "شاخص دلار DXY",
        "expected_sign_for_us30": -1,
        "measured_corr_2y": -0.012,
        "t_stat": -0.27,
        "directional_weight": 0.0,
        "verdict": "برای داوجونز وتوی جهت‌دار نیست؛ فقط اطلاعات زمینه‌ای.",
    },
    "^TNX": {
        "key": "us10y",
        "name": "بازده ۱۰ ساله آمریکا",
        "expected_sign_for_us30": -1,
        "t_stat": -1.50,
        "directional_weight": 0.18,
        "verdict": "ضعیف؛ فقط جهش‌های بزرگ به‌عنوان هشدار فشار سهام.",
    },
    "^GSPC": {"key": "spx", "name": "S&P 500", "expected_sign_for_us30": 1, "directional_weight": 1.0},
    "^NDX": {"key": "ndx", "name": "Nasdaq 100", "expected_sign_for_us30": 1, "directional_weight": 1.0},
    "^VIX": {"key": "vix", "name": "VIX", "expected_sign_for_us30": -1, "directional_weight": 0.35, "verdict": "هشدار نوسان/ریسک شکست جعلی؛ وتوی خرید دائمی نیست."},
}

SMT_PEERS_US30 = ["^GSPC", "^NDX"]

BROKER_TRENDO = {
    "broker": "Trendo",
    "symbol_equivalent": "FOREXCOM:US30",
    "observed_platform_diff": "حدود ۴ سنت",
    "spread_rule": "عدد نمایش‌داده‌شده = تعداد واحد در آخرین رقم اعشار",
    "spreads_points": {
        "ny_session_tehran_17_23": 0.70,
        "other_hours": 2.10,
    },
    "account_example": {
        "balance_usd": 10.0,
        "leverage": 50,
        "min_lot": 0.01,
        "per_point_per_1lot_usd": 1.0,
        "price_reference": 50844,
        "contract_value_001_lot_usd": 508.44,
        "required_margin_usd": 10.17,
        "verdict": "با ۱۰ دلار، ۰.۰۱ لات US30 باز نمی‌شود؛ حدود ۰.۱۷ دلار کسری مارجین دارد.",
    },
}

CONTRACT = {
    "US30": {"unit": "واحد", "per_point": 1.0, "lot_name": "قرارداد (۱$ هر واحد)", "decimals": 2},
    "XAUUSD": {"unit": "اونس", "per_point": 100.0, "lot_name": "لات (۱۰۰ اونس)"},
}

KILLZONES_TEHRAN_SUMMER = [
    {"key": "asia", "name": "دامنه آسیا", "start": "04:00", "end": "09:30", "weight": 0.35},
    {"key": "london", "name": "باز شدن لندن", "start": "11:30", "end": "14:30", "weight": 0.85},
    {"key": "ny_pre", "name": "پیش‌گشایش نیویورک", "start": "16:30", "end": "17:00", "weight": 0.30},
    {"key": "ny_am", "name": "باز شدن نیویورک", "start": "17:00", "end": "20:00", "weight": 1.00},
    {"key": "ny_pm", "name": "بعدازظهر نیویورک", "start": "20:00", "end": "22:30", "weight": 0.55},
    {"key": "ny_close", "name": "بسته شدن", "start": "22:30", "end": "23:30", "weight": 0.20},
]

ENGINE_CONSTANTS = {
    "threshold": {"US30": {"minimum": 32.0, "strong": 40.0, "evidence_n": 144, "win_rate": 56.9, "avg_r": 0.399, "t": 3.98}},
    "best_r": {"US30": 2.5, "XAUUSD": 2.0},
    "bad_intervals": ["1h", "5m", "15m", "30m"],
    "cost_pct_round_trip": {"US30": 0.012, "XAUUSD": 0.020},
    "horizon_bars": {"5m": 12, "15m": 8, "30m": 6, "1h": 8, "1d": 5},
    "validated_plan": {"stop_atr": 1.0, "rr_us30": 2.5, "plan_none_when_qualifies_false": True},
}

US30_MEASURED_NUMBERS = {
    "atr_by_tf": {
        "1d": {"recent": 510, "long": 570, "risk_001_lot_usd": 5.10, "account_for_2pct_risk_usd": 255},
        "4h": {"recent": 382, "long": 410, "risk_001_lot_usd": 3.82, "account_for_2pct_risk_usd": 191},
        "1h": {"recent": 168, "long": 164, "risk_001_lot_usd": 1.68, "account_for_2pct_risk_usd": 84},
        "15m": {"recent": 48, "long": 79, "risk_001_lot_usd": 0.48, "account_for_2pct_risk_usd": 24},
        "5m": {"recent": 25, "long": 43, "risk_001_lot_usd": 0.25, "account_for_2pct_risk_usd": 13},
    },
    "hourly_profile_trendo": {
        "17": {"range_5m": 65.0, "spread": 0.70, "range_spread": 92.9, "rank": "best"},
        "18": {"range_5m": 44.0, "spread": 0.70, "range_spread": 62.9},
        "19": {"range_5m": 33.0, "spread": 0.70, "range_spread": 47.1},
        "20": {"range_5m": 28.0, "spread": 0.70, "range_spread": 40.0},
        "21": {"range_5m": 24.0, "spread": 0.70, "range_spread": 34.3},
        "22": {"range_5m": 23.0, "spread": 0.70, "range_spread": 32.9},
        "23": {"range_5m": 25.0, "spread": 0.70, "range_spread": 35.7},
    },
    "ny_first_15m_range_percentiles": {"p10": 81, "p25": 105, "p50": 143, "p75": 192, "p90": 245},
    "timeframe_edge": {
        "1d": {"avg_r": 0.201, "engine_avg_r": 0.399, "t": 3.98, "status": "معنادار"},
        "4h": {"avg_r": 0.016, "t": 1.46, "status": "نامعتبر"},
        "1h": {"avg_r": -0.017, "engine_avg_r": -0.077, "t": 0.98, "status": "نامعتبر"},
        "5m": {"avg_r": 0.025, "t": 0.62, "status": "نامعتبر"},
        "1m": {"avg_r": -0.083, "t": -7.25, "status": "قطعاً بد"},
    },
    "scalp_tick_backtest": {
        "ticks": 61_000_000,
        "trades": 46_708,
        "profitable_with_real_spread": "2 از 32",
        "profitable_if_free": "12 از 32",
        "bonferroni_significant": 0,
        "historical_median_spread_plus_slippage": 3.49,
        "annual_cost_at_5_trades_day_pct": 11.8,
    },
    "orb_76_search": {
        "bonferroni_threshold_abs_t": 3.4,
        "significant_after_bonferroni": 0,
        "best_survivor": {"name": "خرید + دامنه بازگشایی کوچک", "n": 176, "win_rate": 41.5, "avg_r": 0.188, "t": 1.72, "worst_loss_streak": 11, "max_drawdown_r": 15.29, "frequency_month": 4.5},
        "yearly_instability": {
            "2023": {"n": 61, "win_rate": 52.5, "avg_r": 0.201},
            "2024": {"n": 251, "win_rate": 39.4, "avg_r": -0.069},
            "2025": {"n": 256, "win_rate": 45.7, "avg_r": 0.095},
            "2026": {"n": 185, "win_rate": 41.1, "avg_r": -0.056},
        },
    },
    "stop_limit_effect": {
        "other_side_box": {"win_rate": 42.3, "avg_r": 0.023, "median_risk_points": 154, "account_for_2pct": 77},
        "cap_50": {"win_rate": 36.1, "avg_r": 0.041, "median_risk_points": 50, "account_for_2pct": 25},
        "cap_20": {"win_rate": 27.9, "avg_r": 0.027, "median_risk_points": 20, "account_for_2pct": 10},
    },
    "golden_hour_ticks": {
        "09:30-10:00_NY": {"candle_range": 33.1, "spread": 2.31, "ticks_per_min": 280, "signal_cost": 14.3, "rank": "best"},
        "10:00-11:00_NY": {"candle_range": 23.5, "spread": 2.30, "ticks_per_min": 228, "signal_cost": 10.2},
        "12:00-14:00_NY": {"candle_range": 16.0, "spread": 2.31, "ticks_per_min": 156, "signal_cost": 6.9, "rank": "avoid"},
    },
}

TRAPS_LEARNED = [
    "/tmp با هر ری‌استارت Render پاک می‌شود؛ انبار باید fallback ریپو داشته باشد.",
    "اندیس timezoneدار یاهو می‌تواند join را خراب کند؛ normalize/tz_localize(None) لازم است.",
    "کندل روزانه یاهو تا چند ساعت بعد از close ممکن است نهایی نباشد.",
    "مسیر cache شده اثبات کد زنده نیست؛ fresh/source را چک کنید.",
    "وتوی DXY برای داوجونز بی‌معناست؛ t=-0.27.",
    "آستانه 32 باید فقط روی score هم‌مقیاس validated.py اعمال شود.",
    "مسیر سنگین بدون semaphore روی Render رایگان سایت را می‌خواباند.",
    "acquire فوری باعث 503 در اولین load می‌شود؛ صبر سقف‌دار بهتر است.",
    "لبه داخل اسپرد زندگی می‌کند؛ همیشه با اسپرد واقعی بروکر تست کنید.",
    "با آزمون‌های زیاد باید Bonferroni لحاظ شود.",
    "تغییر حد ضرر یعنی استراتژی جدید و بک‌تست جدید.",
]

INFRA_REFERENCE = {
    "hosting": "Render free",
    "resources": "0.1 CPU / 512 MB / single worker recommended",
    "sleep_after_idle_min": 15,
    "snapshot_defaults": {"SNAPSHOT_PATH": "/tmp/dow_snapshot.json", "SNAPSHOT_REFRESH_AFTER": 900, "SNAPSHOT_MAX_AGE": 14400, "REMOTE_TTL": 300, "HEAVY_WAIT_SEC": 12},
    "legacy_flask_command": "gunicorn wsgi:app --bind 0.0.0.0:$PORT --workers 1 --threads 8 --timeout 600",
    "fastapi_command_current": "uvicorn server:app --host 0.0.0.0 --port $PORT --proxy-headers",
}

IF_BUILD_FROM_ZERO = [
    "^DJI برای قیمت، DIA برای کندل، YM=F منهای basis برای ساعات بسته.",
    "cache + semaphore + صبر سقف‌دار برای همه مسیرهای سنگین.",
    "انبار روی دیسک و ریپو؛ /tmp پاک می‌شود.",
    "هر عدد با منبع و t؛ عدد بدون t فقط تزیین است.",
    "فقط daily برای معامله؛ intraday فقط نمایش/timing.",
    "اسپرد واقعی بروکر از کاربر گرفته شود.",
    "هر جدول UI توضیح ساده داشته باشد.",
    "چیزی که قابل اندازه‌گیری نیست حذف شود.",
]


def as_dict() -> Dict[str, Any]:
    return {
        "yahoo": {"endpoint": YAHOO_CHART_ENDPOINT, "headers": YAHOO_REQUIRED_HEADERS, "limits": YAHOO_INTERVAL_LIMITS},
        "symbol_roles": US30_SYMBOL_ROLES,
        "intermarket_measured": INTERMARKET_MEASURED,
        "smt_peers": SMT_PEERS_US30,
        "broker_trendo": BROKER_TRENDO,
        "contract": CONTRACT,
        "killzones_tehran_summer": KILLZONES_TEHRAN_SUMMER,
        "engine_constants": ENGINE_CONSTANTS,
        "measured_numbers": US30_MEASURED_NUMBERS,
        "traps_learned": TRAPS_LEARNED,
        "infra_reference": INFRA_REFERENCE,
        "if_build_from_zero": IF_BUILD_FROM_ZERO,
    }
