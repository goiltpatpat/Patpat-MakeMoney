#!/usr/bin/env python3
"""Unit tests for pmm_gates (fail-closed + flag defaults)."""
from __future__ import annotations

import unittest
from unittest.mock import patch

import pmm_gates as g


class GateUnitTests(unittest.TestCase):
    def test_impulse_disabled_passes(self):
        r = g.evaluate_impulse("btc-updown-5m-1", enabled=False, btc_move_usd_min=80)
        self.assertTrue(r.ok)
        self.assertEqual(r.status, "impulse_gate_disabled")

    def test_impulse_below_min_fail_closed(self):
        g._OPEN_PX.clear()
        with patch.object(g, "fetch_binance_btcusdt", side_effect=[(100000.0, __import__("time").time()), (100050.0, __import__("time").time())]):
            # ensure_btc_open uses first fetch; evaluate uses second for now — patch ensure path
            pass
        g._OPEN_PX["btc-updown-5m-1"] = 100000.0
        with patch.object(g, "fetch_binance_btcusdt", return_value=(100050.0, __import__("time").time())):
            r = g.evaluate_impulse("btc-updown-5m-1", enabled=True, btc_move_usd_min=80)
        self.assertFalse(r.ok)
        self.assertEqual(r.status, "skip_impulse_below_min")

    def test_impulse_pass_and_soft_max_flag(self):
        g._OPEN_PX["btc-updown-5m-2"] = 100000.0
        with patch.object(g, "fetch_binance_btcusdt", return_value=(100120.0, __import__("time").time())):
            r = g.evaluate_impulse("btc-updown-5m-2", enabled=True, btc_move_usd_min=80, btc_move_usd_max_reference=100)
        self.assertTrue(r.ok)
        self.assertEqual(r.impulse_dir, "UP")
        self.assertTrue(r.flag_above_max_ref)

    def test_impulse_feed_error_fail_closed(self):
        g._OPEN_PX.clear()
        with patch.object(g, "fetch_binance_btcusdt", side_effect=RuntimeError("boom")):
            r = g.evaluate_impulse("btc-updown-5m-3", enabled=True, btc_move_usd_min=80)
        self.assertFalse(r.ok)
        self.assertEqual(r.status, "skip_impulse_feed_unavailable")

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
