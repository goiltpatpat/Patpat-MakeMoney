#!/usr/bin/env python3
"""Unit tests for pmm_gates (fail-closed + flag defaults)."""
from __future__ import annotations

import unittest
from unittest.mock import patch

import pmm_gates as g


class GateUnitTests(unittest.TestCase):
    def setUp(self):
        g._OPEN_PX.clear()

    def test_impulse_disabled_passes(self):
        r = g.evaluate_impulse("btc-updown-5m-1", enabled=False, btc_move_usd_min=80)
        self.assertTrue(r.ok)
        self.assertEqual(r.status, "impulse_gate_disabled")

    def test_bucket_open_from_slug(self):
        self.assertEqual(g.bucket_open_ts_from_slug("btc-updown-5m-1788663900"), 1788663900)

    def test_impulse_uses_bucket_open_kline(self):
        with patch.object(g, "fetch_binance_btc_open_at", return_value=100000.0) as open_fn, \
             patch.object(g, "fetch_binance_btcusdt", return_value=100090.0):
            r = g.evaluate_impulse("btc-updown-5m-1788663900", enabled=True, btc_move_usd_min=80)
        open_fn.assert_called()
        self.assertEqual(open_fn.call_args[0][0], 1788663900)
        self.assertTrue(r.ok)
        self.assertEqual(r.impulse_dir, "UP")
        self.assertEqual(r.btc_open, 100000.0)
        self.assertEqual(r.btc_move_usd, 90.0)

    def test_impulse_below_min_fail_closed(self):
        with patch.object(g, "fetch_binance_btc_open_at", return_value=100000.0), \
             patch.object(g, "fetch_binance_btcusdt", return_value=100050.0):
            r = g.evaluate_impulse("btc-updown-5m-1788663900", enabled=True, btc_move_usd_min=80)
        self.assertFalse(r.ok)
        self.assertEqual(r.status, "skip_impulse_below_min")

    def test_impulse_open_unavailable(self):
        with patch.object(g, "fetch_binance_btc_open_at", side_effect=RuntimeError("binance_kline_empty")):
            r = g.evaluate_impulse("btc-updown-5m-1788663900", enabled=True, btc_move_usd_min=80)
        self.assertFalse(r.ok)
        self.assertEqual(r.status, "skip_impulse_open_unavailable")

    def test_impulse_feed_error_fail_closed(self):
        with patch.object(g, "fetch_binance_btc_open_at", return_value=100000.0), \
             patch.object(g, "fetch_binance_btcusdt", side_effect=RuntimeError("boom")):
            r = g.evaluate_impulse("btc-updown-5m-1788663900", enabled=True, btc_move_usd_min=80)
        self.assertFalse(r.ok)
        self.assertEqual(r.status, "skip_impulse_feed_unavailable")

    def test_impulse_pass_and_soft_max_flag(self):
        with patch.object(g, "fetch_binance_btc_open_at", return_value=100000.0), \
             patch.object(g, "fetch_binance_btcusdt", return_value=100120.0):
            r = g.evaluate_impulse("btc-updown-5m-1788663900", enabled=True, btc_move_usd_min=80, btc_move_usd_max_reference=100)
        self.assertTrue(r.ok)
        self.assertEqual(r.impulse_dir, "UP")
        self.assertTrue(r.flag_above_max_ref)

    def test_skew_against_impulse(self):
        r = g.evaluate_skew(0.60, 0.75, enabled=True, impulse_dir="UP", require_align=True)
        self.assertFalse(r.ok)
        self.assertEqual(r.status, "skip_skew_against_impulse")
        self.assertEqual(r.skew_side, "DOWN")

    def test_skew_align_pass(self):
        r = g.evaluate_skew(0.80, 0.55, enabled=True, impulse_dir="UP", require_align=True)
        self.assertTrue(r.ok)
        self.assertEqual(r.skew_side, "UP")

    def test_filter_anti_impulse(self):
        kept, status = g.filter_candidates_by_impulse([("DOWN", 0.8)], "UP", enabled=True)
        self.assertEqual(kept, [])
        self.assertEqual(status, "skip_threshold_anti_impulse_only")


if __name__ == "__main__":
    unittest.main()
