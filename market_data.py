#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
market_data.py — provider layer for the dedicated US30 dashboard.

Architecture note:
- The crypto ASEMAN project used a clean API/fetcher separation.
- This file gives US30 the same separation: the analysis engine never knows
  whether candles came from Yahoo, TwelveData, Polygon, Finnhub, or AlphaVantage.

Default mode is Yahoo/DIA with DISPLAY_SCALE=100 because DIA has stable free
historical candles and DIA × 100 is a practical US30/DJ30 display proxy.
For a paid real US30 feed, set DATA_PROVIDER, DATA_API_KEY, DATA_SYMBOL and
DISPLAY_SCALE=1 in Render environment variables.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional, Tuple
from urllib.parse import quote

import pandas as pd
import requests


INTERVAL_PERIODS = {
    "5m": "60d",
    "15m": "60d",
    "30m": "60d",
    "1h": "730d",
    "1d": "5y",
}

VALID_INTERVALS = tuple(INTERVAL_PERIODS.keys())

YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
YAHOO_HEADERS = {"User-Agent": "Mozilla/5.0"}


@dataclass
class FetchResult:
    df: pd.DataFrame
    provider: str
    symbol: str
    source_note: str
    fetched_at: float
    display_scale: float
    raw_price_is_index: bool = False


def _env(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


def _bool_env(name: str, default: bool = False) -> bool:
    v = _env(name, "true" if default else "false").lower()
    return v in {"1", "true", "yes", "on", "y"}


def selected_provider() -> str:
    return _env("DATA_PROVIDER", "yahoo").lower() or "yahoo"


def selected_symbol() -> str:
    return _env("DATA_SYMBOL", "DIA") or "DIA"


def request_timeout() -> float:
    try:
        return max(3.0, float(_env("REQUEST_TIMEOUT", "10")))
    except Exception:
        return 10.0


def display_scale_for(symbol: Optional[str] = None) -> float:
    raw = _env("DISPLAY_SCALE", "")
    if raw:
        try:
            return float(raw)
        except Exception:
            pass
    sym = (symbol or selected_symbol()).upper().strip()
    # DIA is an ETF trading around 1/100 of the Dow Jones index.
    return 100.0 if sym in {"DIA", "NYSEARCA:DIA"} else 1.0


def _normalize_df(df: pd.DataFrame) -> pd.DataFrame:
    """Return a clean OHLCV dataframe with columns Open/High/Low/Close/Volume."""
    if df is None or df.empty:
        raise RuntimeError("داده کندلی خالی است")

    rename = {
        "open": "Open", "high": "High", "low": "Low", "close": "Close", "volume": "Volume",
        "o": "Open", "h": "High", "l": "Low", "c": "Close", "v": "Volume",
    }
    df = df.rename(columns={c: rename.get(str(c), c) for c in df.columns})
    need = ["Open", "High", "Low", "Close"]
    for c in need:
        if c not in df.columns:
            raise RuntimeError(f"ستون {c} در داده provider وجود ندارد")
    if "Volume" not in df.columns:
        df["Volume"] = 0.0

    out = df[["Open", "High", "Low", "Close", "Volume"]].copy()
    for c in out.columns:
        out[c] = pd.to_numeric(out[c], errors="coerce")
    out = out.dropna(subset=need, how="any")
    out = out[~out.index.duplicated(keep="last")]
    out = out.sort_index()
    if out.empty:
        raise RuntimeError("پس از پاکسازی داده، کندلی باقی نماند")
    try:
        if getattr(out.index, "tz", None) is not None:
            out.index = out.index.tz_convert(None)
    except Exception:
        try:
            out.index = out.index.tz_localize(None)
        except Exception:
            pass
    return out


def _fetch_yahoo_chart_json(symbol: str, interval: str, period: str, include_prepost: bool = False) -> Dict:
    """Direct Yahoo chart endpoint used in dow-analyzer1.

    The explicit User-Agent is intentional; without it Yahoo often returns 429.
    """
    url = YAHOO_CHART_URL.format(symbol=quote(symbol, safe=""))
    params = {
        "interval": interval,
        "range": period,
        "includePrePost": "true" if include_prepost else "false",
    }
    r = requests.get(url, params=params, headers=YAHOO_HEADERS, timeout=request_timeout())
    r.raise_for_status()
    j = r.json()
    err = (j.get("chart") or {}).get("error")
    if err:
        raise RuntimeError(err.get("description") or err.get("code") or "Yahoo chart error")
    res = (j.get("chart") or {}).get("result") or []
    if not res:
        raise RuntimeError("Yahoo chart result خالی است")
    return res[0]


def _yahoo_result_to_df(res: Dict) -> pd.DataFrame:
    ts = res.get("timestamp") or []
    q = ((res.get("indicators") or {}).get("quote") or [{}])[0]
    opens = q.get("open") or []
    highs = q.get("high") or []
    lows = q.get("low") or []
    closes = q.get("close") or []
    vols = q.get("volume") or []
    rows = []
    for i, t in enumerate(ts):
        try:
            o, h, l, c = opens[i], highs[i], lows[i], closes[i]
            if o is None or h is None or l is None or c is None:
                continue
            rows.append({
                "time": pd.to_datetime(int(t), unit="s", utc=True),
                "Open": o, "High": h, "Low": l, "Close": c,
                "Volume": 0 if i >= len(vols) or vols[i] is None else vols[i],
            })
        except Exception:
            continue
    if not rows:
        raise RuntimeError("Yahoo candles بعد از فیلتر None خالی شد")
    return pd.DataFrame(rows).set_index("time")


def fetch_yahoo(interval: str, bars: int, symbol: Optional[str] = None) -> FetchResult:
    sym = symbol or selected_symbol() or "DIA"
    period = INTERVAL_PERIODS.get(interval, "1y")
    include_prepost = _bool_env("YAHOO_INCLUDE_PREPOST", False)
    res = _fetch_yahoo_chart_json(sym, interval, period, include_prepost=include_prepost)
    df = _normalize_df(_yahoo_result_to_df(res))
    return FetchResult(
        df=df,
        provider="yahoo_chart",
        symbol=sym,
        source_note=f"Yahoo Finance chart endpoint / {sym} / UA Mozilla/5.0",
        fetched_at=time.time(),
        display_scale=display_scale_for(sym),
        raw_price_is_index=(display_scale_for(sym) == 1.0),
    )


def _require_key(provider: str) -> str:
    key = _env("DATA_API_KEY")
    if not key:
        raise RuntimeError(f"DATA_API_KEY برای provider={provider} تنظیم نشده است")
    return key


def fetch_twelvedata(interval: str, bars: int) -> FetchResult:
    key = _require_key("twelvedata")
    sym = selected_symbol() or "DIA"
    td_interval = {"5m": "5min", "15m": "15min", "30m": "30min", "1h": "1h", "1d": "1day"}.get(interval, interval)
    outputsize = max(120, min(5000, int(bars) + 260))
    url = "https://api.twelvedata.com/time_series"
    params = {
        "symbol": sym,
        "interval": td_interval,
        "outputsize": outputsize,
        "apikey": key,
        "format": "JSON",
    }
    r = requests.get(url, params=params, timeout=request_timeout())
    r.raise_for_status()
    j = r.json()
    if j.get("status") == "error":
        raise RuntimeError(j.get("message") or "TwelveData error")
    values = j.get("values") or []
    if not values:
        raise RuntimeError("TwelveData candle values خالی است")
    rows = []
    for x in values:
        rows.append({
            "time": pd.to_datetime(x.get("datetime")),
            "Open": x.get("open"), "High": x.get("high"),
            "Low": x.get("low"), "Close": x.get("close"),
            "Volume": x.get("volume", 0),
        })
    df = pd.DataFrame(rows).set_index("time")
    df = _normalize_df(df)
    return FetchResult(df, "twelvedata", sym, f"TwelveData / {sym}", time.time(), display_scale_for(sym), display_scale_for(sym) == 1.0)


def _polygon_range(interval: str) -> Tuple[int, str, int]:
    if interval.endswith("m"):
        return int(interval[:-1]), "minute", 75
    if interval == "1h":
        return 1, "hour", 900
    return 1, "day", 2200


def fetch_polygon(interval: str, bars: int) -> FetchResult:
    key = _require_key("polygon")
    sym = selected_symbol() or "DIA"
    mult, span, days = _polygon_range(interval)
    end = datetime.now(timezone.utc).date()
    start = end - timedelta(days=days)
    url = f"https://api.polygon.io/v2/aggs/ticker/{quote(sym, safe=':')}/range/{mult}/{span}/{start}/{end}"
    params = {"adjusted": "true", "sort": "asc", "limit": 50000, "apiKey": key}
    r = requests.get(url, params=params, timeout=request_timeout())
    r.raise_for_status()
    j = r.json()
    if j.get("status") not in {"OK", "DELAYED"} and not j.get("results"):
        raise RuntimeError(j.get("error") or j.get("message") or "Polygon error")
    rows = []
    for x in j.get("results") or []:
        rows.append({
            "time": pd.to_datetime(int(x["t"]), unit="ms"),
            "Open": x.get("o"), "High": x.get("h"), "Low": x.get("l"),
            "Close": x.get("c"), "Volume": x.get("v", 0),
        })
    if not rows:
        raise RuntimeError("Polygon results خالی است")
    df = pd.DataFrame(rows).set_index("time")
    df = _normalize_df(df)
    return FetchResult(df, "polygon", sym, f"Polygon / {sym}", time.time(), display_scale_for(sym), display_scale_for(sym) == 1.0)


def fetch_finnhub(interval: str, bars: int) -> FetchResult:
    key = _require_key("finnhub")
    sym = selected_symbol() or "DIA"
    res = {"5m": "5", "15m": "15", "30m": "30", "1h": "60", "1d": "D"}.get(interval, "60")
    now = int(time.time())
    days = {"5m": 70, "15m": 70, "30m": 90, "1h": 730, "1d": 2200}.get(interval, 730)
    start = now - days * 86400
    url = "https://finnhub.io/api/v1/stock/candle"
    params = {"symbol": sym, "resolution": res, "from": start, "to": now, "token": key}
    r = requests.get(url, params=params, timeout=request_timeout())
    r.raise_for_status()
    j = r.json()
    if j.get("s") != "ok":
        raise RuntimeError(j.get("error") or f"Finnhub status={j.get('s')}")
    rows = []
    for t, o, h, l, c, v in zip(j.get("t", []), j.get("o", []), j.get("h", []), j.get("l", []), j.get("c", []), j.get("v", [])):
        rows.append({"time": pd.to_datetime(int(t), unit="s"), "Open": o, "High": h, "Low": l, "Close": c, "Volume": v})
    if not rows:
        raise RuntimeError("Finnhub candles خالی است")
    df = pd.DataFrame(rows).set_index("time")
    df = _normalize_df(df)
    return FetchResult(df, "finnhub", sym, f"Finnhub / {sym}", time.time(), display_scale_for(sym), display_scale_for(sym) == 1.0)


def fetch_alphavantage(interval: str, bars: int) -> FetchResult:
    key = _require_key("alphavantage")
    sym = selected_symbol() or "DIA"
    base = "https://www.alphavantage.co/query"
    if interval == "1d":
        params = {"function": "TIME_SERIES_DAILY_ADJUSTED", "symbol": sym, "outputsize": "full", "apikey": key}
        series_key = "Time Series (Daily)"
    else:
        av_interval = {"5m": "5min", "15m": "15min", "30m": "30min", "1h": "60min"}.get(interval, "60min")
        params = {"function": "TIME_SERIES_INTRADAY", "symbol": sym, "interval": av_interval, "outputsize": "full", "apikey": key}
        series_key = f"Time Series ({av_interval})"
    r = requests.get(base, params=params, timeout=request_timeout())
    r.raise_for_status()
    j = r.json()
    if "Error Message" in j:
        raise RuntimeError(j["Error Message"])
    if "Note" in j:
        raise RuntimeError(j["Note"])
    series = j.get(series_key) or {}
    if not series:
        # find a time series key defensively
        for k, v in j.items():
            if k.lower().startswith("time series") and isinstance(v, dict):
                series = v
                break
    if not series:
        raise RuntimeError("AlphaVantage time series خالی است")
    rows = []
    for ts, x in series.items():
        rows.append({
            "time": pd.to_datetime(ts),
            "Open": x.get("1. open"), "High": x.get("2. high"),
            "Low": x.get("3. low"), "Close": x.get("4. close"),
            "Volume": x.get("6. volume") or x.get("5. volume") or 0,
        })
    df = pd.DataFrame(rows).set_index("time")
    df = _normalize_df(df)
    return FetchResult(df, "alphavantage", sym, f"AlphaVantage / {sym}", time.time(), display_scale_for(sym), display_scale_for(sym) == 1.0)


_PROVIDER_FUNCS = {
    "yahoo": fetch_yahoo,
    "twelvedata": fetch_twelvedata,
    "twelve_data": fetch_twelvedata,
    "polygon": fetch_polygon,
    "finnhub": fetch_finnhub,
    "alphavantage": fetch_alphavantage,
    "alpha_vantage": fetch_alphavantage,
}


def fetch_ohlcv(interval: str = "1h", bars: int = 180, provider: Optional[str] = None) -> FetchResult:
    interval = interval if interval in VALID_INTERVALS else _env("DEFAULT_INTERVAL", "1h")
    bars = max(80, min(int(bars or 180), 600))
    prov = (provider or selected_provider()).lower().strip() or "yahoo"
    fn = _PROVIDER_FUNCS.get(prov)
    if fn is None:
        raise RuntimeError(f"DATA_PROVIDER نامعتبر است: {prov}")

    errors = []
    try:
        if prov == "yahoo":
            return fetch_yahoo(interval, bars)
        return fn(interval, bars)  # type: ignore[misc]
    except Exception as e:
        errors.append(f"{prov}: {e}")
        if prov != "yahoo" and _bool_env("DATA_FALLBACK", True):
            try:
                out = fetch_yahoo(interval, bars, symbol="DIA")
                out.provider = f"{prov}->yahoo_fallback"
                out.source_note = f"Fallback Yahoo/DIA after {errors[0]}"
                return out
            except Exception as e2:
                errors.append(f"yahoo fallback: {e2}")
    raise RuntimeError(" | ".join(errors))


def provider_status() -> Dict[str, object]:
    key = _env("DATA_API_KEY")
    masked = ""
    if key:
        masked = key[:4] + "*" * max(0, len(key) - 8) + key[-4:] if len(key) > 8 else "****"
    return {
        "provider": selected_provider(),
        "symbol": selected_symbol(),
        "display_scale": display_scale_for(),
        "has_api_key": bool(key),
        "masked_api_key": masked,
        "fallback": _bool_env("DATA_FALLBACK", True),
        "valid_intervals": list(VALID_INTERVALS),
    }
