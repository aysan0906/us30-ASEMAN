#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
bookmap_engine.py — Institutional Order Book Heatmap & Resting Liquidity Engine for Dow Jones (US30).
Simulates Wall Street Level 2/3 Order Book Depth, resting institutional limit order walls,
liquidity sweeps, and iceberg execution detection aligned with live TradingView FOREXCOM:US30 prices.
Supports interactive multi-timeframe scaling (1m, 5m, 15m, 1h, 4h).
"""

from __future__ import annotations
import time
import math
from typing import Dict, Any, List, Optional
import us30_engine as engine

_BM_CACHE: Dict[str, Any] = {}
_BM_CACHE_TIME: Dict[str, float] = {}

def get_us30_bookmap_data(timeframe: str = "15m") -> Dict[str, Any]:
    global _BM_CACHE, _BM_CACHE_TIME
    now = time.time()
    tf_clean = str(timeframe or "15m").lower()
    cached = _BM_CACHE.get(tf_clean)
    if cached and (now - _BM_CACHE_TIME.get(tf_clean, 0.0) < 3.0):
        return cached

    t_data = engine.ticker("1h")
    p_curr = float(t_data.get("price", 51240.0) or 51240.0)
    chg = float(t_data.get("change", 0.0) or 0.0)

    tf_configs = {
        "1m": {"step": 6.0, "w1": 15.0, "w2": 30.0, "w3": 55.0, "w4": 80.0, "name": "۱ دقیقه‌ای اسکالپ"},
        "5m": {"step": 12.0, "w1": 25.0, "w2": 60.0, "w3": 110.0, "w4": 160.0, "name": "۵ دقیقه‌ای مومنتوم"},
        "15m": {"step": 25.0, "w1": 45.0, "w2": 95.0, "w3": 160.0, "w4": 240.0, "name": "۱۵ دقیقه‌ای استاندارد"},
        "1h": {"step": 55.0, "w1": 90.0, "w2": 180.0, "w3": 310.0, "w4": 480.0, "name": "۱ ساعته دی‌ترید"},
        "4h": {"step": 130.0, "w1": 200.0, "w2": 420.0, "w3": 750.0, "w4": 1100.0, "name": "۴ ساعته سوئینگ"},
    }
    cfg = tf_configs.get(tf_clean, tf_configs["15m"])
    base_step = cfg["step"]

    # 1. Ask Liquidity Walls (Resting Institutional Sell Orders above price)
    # Higher volume = hotter color on heatmap
    ask_levels: List[Dict[str, Any]] = [
        {
            "price": round(p_curr + cfg["w1"], 1),
            "volume_lots": 1420,
            "depth_pct": 48,
            "heat_color": "#38bdf8",
            "type": "ASK_WALL",
            "label": "نقدینگی اسکالپ سشن",
            "distance_pts": cfg["w1"],
            "note": "سفارشات فروش فعال الگوریتم‌های HFT"
        },
        {
            "price": round(p_curr + cfg["w2"], 1),
            "volume_lots": 2350,
            "depth_pct": 68,
            "heat_color": "#00d2ff",
            "type": "RESISTANCE_BLOCK",
            "label": "اوردربلاک عرضه میانه",
            "distance_pts": cfg["w2"],
            "note": "دیوار فروش بانک‌های تجاری"
        },
        {
            "price": round(p_curr + cfg["w3"], 1),
            "volume_lots": 3680,
            "depth_pct": 86,
            "heat_color": "#fb923c",
            "type": "MAJOR_BSL",
            "label": "استخر نقدینگی خرید (BSL)",
            "distance_pts": cfg["w3"],
            "note": "هدف اصلی شکار استاپ‌های معامله‌گران خرد"
        },
        {
            "price": round(p_curr + cfg["w4"], 1),
            "volume_lots": 4850,
            "depth_pct": 98,
            "heat_color": "#ffd700",
            "type": "IRON_CEILING",
            "label": "دیوار بتنی سنگین فروش (Golden Wall)",
            "distance_pts": cfg["w4"],
            "note": "سقف توزیع سنگین وال‌استریت و لیمیت‌های هج‌فاندها"
        }
    ]

    # 2. Bid Liquidity Shelves (Resting Institutional Buy Orders below price)
    bid_levels: List[Dict[str, Any]] = [
        {
            "price": round(p_curr - cfg["w1"], 1),
            "volume_lots": 1580,
            "depth_pct": 52,
            "heat_color": "#34d399",
            "type": "BID_SHELF",
            "label": "سپر تقاضای کف سشن",
            "distance_pts": cfg["w1"],
            "note": "تجمع لیمیت‌های خرید نهادی در پولبک"
        },
        {
            "price": round(p_curr - cfg["w2"], 1),
            "volume_lots": 2720,
            "depth_pct": 74,
            "heat_color": "#00e676",
            "type": "DEMAND_BLOCK",
            "label": "سنگر خرید گلدمن ساکس",
            "distance_pts": cfg["w2"],
            "note": "حمایت پرحجم سرمایه‌های بزرگ سازمانی"
        },
        {
            "price": round(p_curr - cfg["w3"], 1),
            "volume_lots": 4120,
            "depth_pct": 91,
            "heat_color": "#00d2ff",
            "type": "MAJOR_SSL",
            "label": "استخر نقدینگی فروش (SSL)",
            "distance_pts": cfg["w3"],
            "note": "ناحیه شکار نقدینگی استاپ‌های زیر کف روز"
        },
        {
            "price": round(p_curr - cfg["w4"], 1),
            "volume_lots": 5240,
            "depth_pct": 100,
            "heat_color": "#a855f7",
            "type": "CONCRETE_FLOOR",
            "label": "کف بتنی حمایتی وال‌استریت (Titanium Floor)",
            "distance_pts": cfg["w4"],
            "note": "سنگین‌ترین کلاستر انباشت خرید ماهانه"
        }
    ]

    # 3. Iceberg Order Tracking
    icebergs: List[Dict[str, Any]] = [
        {
            "price": round(p_curr + cfg["w2"], 1),
            "revealed_vol": 250,
            "estimated_hidden_vol": 2100,
            "direction": "SELL",
            "direction_fa": "فروش پنهان",
            "color": "#ff3366",
            "status": "در حال جذب سفارشات خرید (Absorbing Buys)"
        },
        {
            "price": round(p_curr - cfg["w2"], 1),
            "revealed_vol": 310,
            "estimated_hidden_vol": 2650,
            "direction": "BUY",
            "direction_fa": "خرید پنهان",
            "color": "#00e676",
            "status": "در حال انباشت مخفیانه نهادی (Secret Accumulation)"
        }
    ]

    # 4. Heatmap Depth Matrix for Canvas Rendering (16 horizontal price slices)
    slices = []
    for i in range(-8, 9):
        p_slice = round(p_curr + i * base_step, 1)
        vol = int(800 + 3200 * math.exp(-((abs(i) - 4) ** 2) / 4.0))
        intensity = min(100, int(vol / 40.0))
        is_above = i > 0
        slices.append({
            "price": p_slice,
            "volume": vol,
            "intensity": intensity,
            "side": "ASK" if is_above else ("BID" if i < 0 else "CURRENT"),
            "color": "#ffd700" if intensity > 80 else ("#fb923c" if intensity > 60 else ("#00d2ff" if is_above else "#00e676"))
        })

    # Total liquidity metrics
    total_ask_vol = sum(a["volume_lots"] for a in ask_levels)
    total_bid_vol = sum(b["volume_lots"] for b in bid_levels)
    imbalance_ratio = round((total_bid_vol - total_ask_vol) / (total_bid_vol + total_ask_vol) * 100.0, 1)
    liquidity_verdict = "🟢 برتری نقدینگی خرید در عمق بازار (Bid Heavy)" if imbalance_ratio > 5 else (
        "🔴 تراکم سنگین دیوارهای فروش در عمق بازار (Ask Heavy)" if imbalance_ratio < -5 else "⚪ توازن حجم دفتر سفارشات"
    )

    res = {
        "ok": True,
        "symbol": "FOREXCOM:US30",
        "current_price": p_curr,
        "price_change": chg,
        "timeframe": tf_clean,
        "timeframe_name_fa": cfg["name"],
        "total_resting_ask_volume": total_ask_vol,
        "total_resting_bid_volume": total_bid_vol,
        "imbalance_pct": imbalance_ratio,
        "verdict_fa": liquidity_verdict,
        "ask_levels": ask_levels,
        "bid_levels": bid_levels,
        "iceberg_orders": icebergs,
        "heatmap_slices": slices,
        "spread_estimate": 1.2,
        "liquidity_state": "ACTIVE_HEATMAP",
        "source": "Bookmap L2/L3 Resting Liquidity Model",
        "updated_at": time.strftime("%Y-%m-%d %H:%M:%S UTC")
    }

    _BM_CACHE[tf_clean] = res
    _BM_CACHE_TIME[tf_clean] = now
    return res

if __name__ == "__main__":
    bm = get_us30_bookmap_data()
    print("Bookmap Price:", bm["current_price"])
    print("Verdict:", bm["verdict_fa"])
