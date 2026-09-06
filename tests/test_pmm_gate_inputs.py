"""Offline regression checks for invalid market prices at gate boundaries."""
from __future__ import annotations

import unittest
from unittest.mock import patch

import pmm_gates as g


class GateInputTests(unittest.TestCase):
    def test_invalid_open_prices_fail_closed(self):
        for price in (float("nan"), float("inf"), -float("inf"), 0, -1, "bad", None):
            with self.subTest(price=price), patch.object(g, "ensure_btc_open", return_value=price), patch.object(
                g, "fetch_binance_btcusdt"
            ) as feed:
                result = g.evaluate_impulse("btc-updown-5m-1", enabled=True, btc_move_usd_min=80)
                self.assertFalse(result.ok)
                self.assertEqual(result.status, "skip_impulse_open_unavailable")
                feed.assert_not_called()

    def test_invalid_current_prices_fail_closed(self):
        for price in (float("nan"), float("inf"), -float("inf"), 0, -1, "bad", None):
            with self.subTest(price=price), patch.object(g, "ensure_btc_open", return_value=100000), patch.object(
                g, "fetch_binance_btcusdt", return_value=price
            ):
                result = g.evaluate_impulse("btc-updown-5m-1", enabled=True, btc_move_usd_min=80)
                self.assertFalse(result.ok)
                self.assertEqual(result.status, "skip_impulse_feed_unavailable")

    def test_invalid_asks_fail_closed_on_either_side(self):
        for price in (float("nan"), float("inf"), -float("inf"), 0, -1, 1.01, "bad", None):
            for asks in ((price, 0.75), (0.75, price)):
                with self.subTest(asks=asks):
                    result = g.evaluate_skew(*asks, enabled=True, impulse_dir="DOWN", require_align=False)
                    self.assertFalse(result.ok)
                    self.assertEqual(result.status, "skip_skew_ask_unavailable")

    def test_disabled_gates_preserve_bypass(self):
        with patch.object(g, "ensure_btc_open") as feed:
            result = g.evaluate_impulse("invalid", enabled=False, btc_move_usd_min=80)
            self.assertTrue(result.ok)
            self.assertEqual(result.status, "impulse_gate_disabled")
            feed.assert_not_called()
        result = g.evaluate_skew(float("nan"), None, enabled=False, impulse_dir=None)
        self.assertTrue(result.ok)
        self.assertEqual(result.status, "skew_gate_disabled")

    def test_valid_probability_boundary_still_passes(self):
        result = g.evaluate_skew(1.0, 0.75, enabled=True, impulse_dir="UP")
        self.assertTrue(result.ok)
        self.assertEqual(result.status, "skew_pass")


if __name__ == "__main__":
    unittest.main()
