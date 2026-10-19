"""SMT/liquidity sweep endpoint intentionally fails closed until real peer OHLCV is connected."""
from typing import Any, Dict

_CACHE: Dict[str, Any] = {}


def get_smt_and_sweep_data(current_price: float | None = None) -> Dict[str, Any]:
    try:
        price = float(current_price) if current_price is not None else None
    except (TypeError, ValueError):
        price = None
    if price is None or price <= 10000:
        return {"ok": False, "error": "US30_PRICE_UNAVAILABLE", "message": "قیمت معتبر داوجونز در دسترس نیست."}
    return {
        "ok": False,
        "current_price": price,
        "error": "PEER_OHLCV_UNAVAILABLE",
        "message": "تشخیص SMT واقعی به کندل‌های هم‌زمان US30، SPX و NDX نیاز دارد؛ خروجی ساختگی تولید نمی‌شود.",
        "smt": None,
        "sweep_hunter": None,
    }
