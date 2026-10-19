"""Regression tests for fail-closed US30 signal and data behavior."""
import os
import sys
import subprocess
import unittest
from unittest.mock import patch

import us30_engine as engine
import us30_unified_signals as unified
import cftc_cot_engine
import bookmap_engine
import smt_and_sweep_engine
import elite_modules
import market_data
import pandas as pd


class FailClosedTests(unittest.TestCase):
    def test_synthetic_sources_are_not_reported_as_live(self):
        self.assertFalse(cftc_cot_engine.get_us30_cot_report().get("ok"))
        self.assertFalse(bookmap_engine.get_us30_bookmap_data().get("ok"))
        self.assertFalse(smt_and_sweep_engine.get_smt_and_sweep_data(52000).get("ok"))
        self.assertFalse(elite_modules.get_gex_and_option_walls(52000).get("ok"))
        self.assertFalse(elite_modules.get_nyse_internals(52000, 100).get("ok"))

    def test_ticker_fails_closed_if_live_and_history_are_missing(self):
        engine._TICKER_CACHE = {}
        engine._TICKER_LAST_TIME = 0.0
        with patch.object(engine, "_live_dow_cash", return_value={"ok": False}), \
             patch.object(engine.md, "fetch_ohlcv", side_effect=RuntimeError("no feed")):
            result = engine.ticker("1h")
        self.assertFalse(result["ok"])
        self.assertIsNone(result["price"])
        self.assertEqual(result["error"], "LIVE_AND_HISTORY_PRICE_UNAVAILABLE")
        self.assertFalse(engine._TICKER_CACHE)

    def test_neutral_unified_signal_survives_two_calls(self):
        neutral = {
            "ok": True,
            "meta": {"symbol": "DIA", "raw_price_is_index": False},
            "price": {"last": 52000},
            "signal": {"direction": 0, "score": 50, "plan": {}},
            "structure": {"bias": 0, "htf_bias": 0},
        }
        with patch.object(engine, "build_analysis", return_value=neutral), \
             patch("trendo_engine.get_trendo_us30_live", return_value={"ok": False}):
            first = unified.get_us30_unified_signals(52000)
            second = unified.get_us30_unified_signals(52000)
        for result in (first, second):
            self.assertTrue(result["ok"])
            self.assertEqual(result["scalp"]["direction_code"], "NEUTRAL")
            self.assertIsNone(result["scalp"]["entry"])
            self.assertEqual(result["swing"]["direction_code"], "NEUTRAL")
            self.assertIsNone(result["swing"]["entry"])

    def test_dia_proxy_cannot_create_actionable_composite_signal(self):
        import server
        proxy_analysis = {
            "ok": True,
            "meta": {"symbol": "DIA", "raw_price_is_index": False, "provider": "test", "source_note": "proxy"},
            "price": {"last": 52000},
            "signal": {"direction": 1, "score": 95, "grade": "A", "plan": {"entry": 52000, "stop": 51900, "tp1": 52100, "tp2": 52200, "tp3": 52300}, "parts": []},
        }
        with patch.object(server.engine, "build_analysis", return_value=proxy_analysis):
            result = server.dow_composite_signal(interval="1h", broker="forexcom")
        self.assertTrue(result["ok"])
        self.assertEqual(result["action"], "WAIT")
        self.assertIsNone(result["stop_loss"])
        self.assertFalse(result["real_index_source"])

    def test_actual_index_source_with_valid_plan_can_be_actionable(self):
        import server
        index_analysis = {
            "ok": True,
            "meta": {"symbol": "FOREXCOM:US30", "raw_price_is_index": True, "provider": "test", "source_note": "fixture"},
            "price": {"last": 52000},
            "signal": {"direction": 1, "score": 82, "grade": "A", "plan": {"entry": 52000, "stop": 51900, "tp1": 52100, "tp2": 52200, "tp3": 52300}, "parts": []},
        }
        with patch.object(server.engine, "build_analysis", return_value=index_analysis), \
             patch.object(server.execguard, "evaluate", return_value={"ok": True, "trade_allowed": True}):
            intraday = server.dow_composite_signal(interval="1h", broker="forexcom")
            daily = server.dow_composite_signal(interval="1d", broker="forexcom")
        self.assertEqual(intraday["action"], "WAIT")
        self.assertEqual(daily["action"], "BUY")
        self.assertEqual(daily["entry_price"], 52000)
        self.assertEqual(daily["stop_loss"], 51900)

    def test_scale_cannot_turn_dia_into_an_index(self):
        old_symbol = os.environ.get("DATA_SYMBOL")
        old_scale = os.environ.get("DISPLAY_SCALE")
        try:
            os.environ["DATA_SYMBOL"] = "DIA"
            os.environ["DISPLAY_SCALE"] = "1"
            self.assertEqual(market_data.display_scale_for(), 100.0)
            self.assertFalse(market_data.is_index_symbol("DIA"))
            os.environ["DATA_SYMBOL"] = "FOREXCOM:US30"
            os.environ["DISPLAY_SCALE"] = "100"
            self.assertEqual(market_data.display_scale_for(), 1.0)
            self.assertTrue(market_data.is_index_symbol("FOREXCOM:US30"))
        finally:
            if old_symbol is None: os.environ.pop("DATA_SYMBOL", None)
            else: os.environ["DATA_SYMBOL"] = old_symbol
            if old_scale is None: os.environ.pop("DISPLAY_SCALE", None)
            else: os.environ["DISPLAY_SCALE"] = old_scale

    def test_invalid_ohlc_rows_are_removed(self):
        idx = pd.to_datetime(["2026-01-01", "2026-01-02"])
        df = pd.DataFrame({
            "Open": [100.0, 105.0], "High": [110.0, 103.0],
            "Low": [95.0, 104.0], "Close": [108.0, 106.0], "Volume": [10, 11]
        }, index=idx)
        cleaned = market_data._normalize_df(df)
        self.assertEqual(len(cleaned), 1)
        self.assertEqual(float(cleaned.iloc[0]["Close"]), 108.0)

    def test_admin_auth_is_fail_closed_without_secret(self):
        from fastapi import HTTPException
        import server
        os.environ.pop("ADMIN_SECRET_KEY", None)
        request = type("RequestStub", (), {"headers": {}, "query_params": {}})()
        with self.assertRaises(HTTPException) as cm:
            server.verify_admin_auth(request)
        self.assertEqual(cm.exception.status_code, 503)

    def test_guard_blocks_proxy_candles(self):
        import server
        proxy = {"ok": True, "meta": {"symbol": "DIA", "raw_price_is_index": False}, "price": {"last": 52000}, "signal": {"direction": 1, "score": 99, "plan": {"entry": 52000, "stop": 51900, "tp1": 52100, "tp2": 52200, "tp3": 52300}}}
        with patch.object(server.engine, "build_analysis", return_value=proxy), patch.object(server.execguard, "evaluate") as guard:
            result = server.dow_guard(interval="1d", bars=180, fresh=True, balance=1000, leverage=50, lot=0.01)
        self.assertFalse(result["trade_allowed"])
        guard.assert_not_called()

    def test_snapshot_writer_has_no_default_secret(self):
        env = os.environ.copy()
        env.pop("SNAPSHOT_KEY", None)
        result = subprocess.run(
            [sys.executable, "-c", "import snapshot, build_snapshot; assert not snapshot.enabled(); assert build_snapshot.main() == 2"],
            cwd=os.path.dirname(os.path.dirname(__file__)), env=env,
            capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
