"""CFTC COT adapter placeholder. No verified live CFTC parser is enabled yet."""
from typing import Any, Dict

def get_us30_cot_report() -> Dict[str, Any]:
    return {
        "ok": False,
        "error": "CFTC_COT_DATA_UNAVAILABLE",
        "message": "داده‌های COT تأییدشده از فایل رسمی CFTC هنوز به‌صورت زنده parse نمی‌شوند؛ مقادیر تاریخی ساختگی ارائه نمی‌شوند.",
        "market": "US30 futures",
        "history_6_weeks": [],
        "history_6_days": [],
    }
