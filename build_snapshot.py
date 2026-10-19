"""Build and securely push a current US30 snapshot; never fall back to stale trade data."""
import json
import os
import sys
import time
import urllib.error
import urllib.request

DEFAULT_SITE = "https://us30-aseman-1.onrender.com"
SITE = (os.environ.get("SITE_URL") or DEFAULT_SITE).rstrip("/")
KEY = os.environ.get("SNAPSHOT_KEY", "").strip()
DATA_SYMBOL = os.environ.get("DATA_SYMBOL", "").strip()
DATA_PROVIDER = os.environ.get("DATA_PROVIDER", "").strip() or None
INTERVAL = (os.environ.get("SNAPSHOT_INTERVAL") or "1d").strip()
ASSETS = [x.strip().upper() for x in (os.environ.get("ASSETS") or "US30").split(",") if x.strip()]


def build_one(asset: str, interval: str) -> dict:
    """Build only if the configured candle symbol is an actual US30 symbol."""
    import market_data as md

    if "US30" not in DATA_SYMBOL.upper() or "DIA" in DATA_SYMBOL.upper():
        raise RuntimeError("DATA_SYMBOL must be a real US30 symbol; DIA/proxy data is not accepted")
    fetched = md.fetch_ohlcv(interval=interval, bars=180, provider=DATA_PROVIDER)
    if "US30" not in str(fetched.symbol).upper() or "DIA" in str(fetched.symbol).upper():
        raise RuntimeError(f"Provider returned non-executable source symbol: {fetched.symbol!r}")

    import agent as agent_mod
    import web_api
    result = agent_mod.decide(
        interval=interval,
        equity=100000,
        with_ml=True,
        with_mtf=True,
        with_coalition=True,
        scale=True,
        asset=asset,
    )
    if not isinstance(result, dict):
        raise RuntimeError("Agent returned a non-object payload")
    result.pop("intelligence", None)
    cleaned = web_api._clean(result)
    if not isinstance(cleaned, dict) or not cleaned:
        raise RuntimeError("Agent returned an empty payload")
    cleaned["snapshot_source"] = str(fetched.symbol)
    cleaned["snapshot_provider"] = str(fetched.provider)
    cleaned["snapshot_is_proxy"] = False
    cleaned["snapshot_built_at"] = time.time()
    return cleaned


def push(items: dict, built_at: float) -> bool:
    body = json.dumps({"items": items, "built_at": built_at}, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        f"{SITE}/api/snapshot",
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-Snapshot-Key": KEY,
            "User-Agent": "us30-snapshot-bot",
        },
    )
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=40) as response:
                result = json.loads(response.read().decode("utf-8"))
            return bool(result.get("ok"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "ignore")[:200]
            print(f"HTTP {exc.code}: {detail}")
            if exc.code in (400, 403, 413):
                return False
        except Exception as exc:
            print(f"Attempt {attempt + 1}: {type(exc).__name__}: {str(exc)[:160]}")
        if attempt < 2:
            time.sleep(5 * (attempt + 1))
    return False


def main() -> int:
    if not KEY:
        print("SNAPSHOT_KEY is not set; refusing to use a default key.", file=sys.stderr)
        return 2
    if "US30" not in DATA_SYMBOL.upper() or "DIA" in DATA_SYMBOL.upper():
        print("DATA_SYMBOL must be a real US30 symbol; refusing proxy data.", file=sys.stderr)
        return 2
    if INTERVAL not in {"1d"}:
        print("Only the validated 1d snapshot interval is currently enabled.", file=sys.stderr)
        return 2

    items = {}
    for asset in ASSETS:
        if asset != "US30":
            print(f"Skipping unsupported asset: {asset}")
            continue
        try:
            items[f"agent:{asset}:{INTERVAL}"] = build_one(asset, INTERVAL)
        except Exception as exc:
            print(f"Snapshot build failed: {type(exc).__name__}: {str(exc)[:240]}", file=sys.stderr)
            return 1

    if not items:
        print("No current snapshot was built; nothing will be pushed.", file=sys.stderr)
        return 1
    ok = push(items, time.time())
    print("Snapshot pushed successfully." if ok else "Snapshot push failed; no stale fallback was published.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
