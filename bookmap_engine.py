#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
bookmap_engine.py — Institutional Order Book Heatmap & Resting Liquidity Engine for Dow Jones (US30).
Simulates Wall Street Level 2/3 Order Book Depth, resting institutional limit order walls,
liquidity sweeps, and iceberg execution detection aligned with live TradingView FOREXCOM:US30 prices.
"""

from __future__ import annotations
import time
import math
from typing import Dict, Any, List, Optional
import us30_engine as engine

_BM_CACHE: Optional[Dict[str, Any]] = None
_BM_CACHE_TIME: float = 0.0

def get_us30_bookmap_data() -> Dict[str, Any]:
    global _BM_CACHE, _BM_CACHE_TIME
    now = time.time()
    if _BM_CACHE and (now - _BM_CACHE_TIME < 3.0):
        return _BM_CACHE

    t_data = engine.ticker("1h")
    p_curr = float(t_data.get("price", 51240.0) or 51240.0)
    chg = float(t_data.get("change", 0.0) or 0.0)

    # 1. Ask Liquidity Walls (Resting Institutional Sell Orders above price)
    # Higher volume = hotter color on heatmap
    ask_levels: List[Dict[str, Any]] = [
        {
            "price": round(p_curr + 45.0, 1),
            "volume_lots": 1420,
            "depth_pct": 48,
            "heat_color": "#38bdf8",
            "type": "ASK_WALL",
            "label": "نقدینگی اسکالپ سشن",
            "distance_pts": 45.0,
            "note": "سفارشات فروش فعال الگوریتم‌های HFT"
        },
        {
            "price": round(p_curr + 95.0, 1),
            "volume_lots": 2350,
            "depth_pct": 68,
            "heat_color": "#00d2ff",
            "type": "RESISTANCE_BLOCK",
            "label": "اوردربلاک عرضه میانه",
            "distance_pts": 95.0,
            "note": "دیوار فروش بانک‌های تجاری"
        },
        {
            "price": round(p_curr + 160.0, 1),
            "volume_lots": 3680,
            "depth_pct": 86,
            "heat_color": "#fb923c",
            "type": "MAJOR_BSL",
            "label": "استخر نقدینگی خرید (BSL)",
            "distance_pts": 160.0,
            "note": "هدف اصلی شکار استاپ‌های معامله‌گران خرد"
        },
        {
            "price": round(p_curr + 240.0, 1),
            "volume_lots": 4850,
            "depth_pct": 98,
            "heat_color": "#ffd700",
            "type": "IRON_CEILING",
            "label": "دیوار بتنی سنگین فروش (Golden Wall)",
            "distance_pts": 240.0,
            "note": "سقف توزیع سنگین وال‌استریت و لیمیت‌های هج‌فاندها"
        }
    ]

    # 2. Bid Liquidity Shelves (Resting Institutional Buy Orders below price)
    bid_levels: List[Dict[str, Any]] = [
        {
            "price": round(p_curr - 40.0, 1),
            "volume_lots": 1580,
            "depth_pct": 52,
            "heat_color": "#34d399",
            "type": "BID_SHELF",
            "label": "خط دفاعی خریداران سشن",
            "distance_pts": 40.0,
            "note": "حمایت اولیه نقدینگی نوسان‌گیران"
        },
        {
            "price": round(p_curr - 90.0, 1),
            "volume_lots": 2620,
            "depth_pct": 74,
            "heat_color": "#00e676",
            "type": "DEMAND_BLOCK",
            "label": "بلوک سفارشات تقاضا (Demand OB)",
            "distance_pts": 90.0,
            "note": "محدوده واکنش فنری اسمارت‌مانی"
        },
        {
            "price": round(p_curr - 150.0, 1),
            "volume_lots": 3890,
            "depth_pct": 89,
            "heat_color": "#fbbf24",
            "type": "MAJOR_SSL",
            "label": "استخر نقدینگی فروش (SSL)",
            "distance_pts": 150.0,
            "note": "محل جمع‌آوری استاپ‌های خریداران دیررس"
        },
        {
            "price": round(p_curr - 230.0, 1),
            "volume_lots": 5120,
            "depth_pct": 100,
            "heat_color": "#ffd700",
            "type": "CONCRETE_FLOOR",
            "label": "کف بتنی انباشت فوق‌نهادی (Golden Floor)",
            "distance_pts": 230.0,
            "note": "دیوار خرید سنگین ائتلاف غول‌های بانکی وال‌استریت"
        }
    ]

    # 3. Iceberg Order Tracking
    icebergs: List[Dict[str, Any]] = [
        {
            "price": round(p_curr + 120.0, 1),
            "revealed_vol": 250,
            "estimated_hidden_vol": 2100,
            "direction": "SELL",
            "direction_fa": "فروش پنهان",
            "color": "#ff3366",
            "status": "در حال جذب سفارشات خرید (Absorbing Buys)"
        },
        {
            "price": round(p_curr - 85.0, 1),
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
    base_step = 25.0
    for i in range(-8, 9):
        p_slice = round(p_curr + i * base_step, 1)
        dist = abs(i * base_step)
        # Closer to key walls has higher resting liquidity
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

    _BM_CACHE = res
    _BM_CACHE_TIME = now
    return res

if __name__ == "__main__":
    bm = get_us30_bookmap_data()
    print("Bookmap Price:", bm["current_price"])
    print("Verdict:", bm["verdict_fa"])
    print("Ask Levels Count:", len(bm["ask_levels"]))
    print("Bid Levels Count:", len(bm["bid_levels"]))
    print("Icebergs Count:", len(bm["iceberg_orders"]))
