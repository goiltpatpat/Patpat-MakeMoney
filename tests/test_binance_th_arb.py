#!/usr/bin/env python3
"""Unit tests for Binance TH tape + DEX→CEX arb scanner (mocked HTTP)."""
from __future__ import annotations

import io
import json
import sys
import unittest
from pathlib import Path
from unittest import mock
from urllib.error import URLError

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
SCRIPTS = ROOT / "scripts"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from venues.arb.dex_cex import (  # noqa: E402
    ArbFeeConfig,
    detect_dex_cex_opportunity,
    simulate_paper_dual_leg,
)
from venues.binance_th import paper as bnth_paper  # noqa: E402
from venues.binance_th import tape as bnth_tape  # noqa: E402
import pmm_arb_scan  # noqa: E402


def _fake_urlopen(payload, status: int = 200):
    raw = payload if isinstance(payload, (bytes, bytearray)) else json.dumps(payload).encode("utf-8")

    class Resp:
        def read(self):
            return raw

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def opener(req, timeout=None):  # noqa: ARG001
        if status >= 400:
            import urllib.error

            raise urllib.error.HTTPError(req.full_url, status, "err", hdrs=None, fp=io.BytesIO(b""))
        return Resp()

    return opener


def _route_urlopen(routes: dict):
    """Map URL substring → payload."""

    class Resp:
        def __init__(self, raw: bytes):
            self._raw = raw

        def read(self):
            return self._raw

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def opener(req, timeout=None):  # noqa: ARG001
        url = req.full_url
        if "api.binance.com" in url:
            raise AssertionError(f"must never call api.binance.com: {url}")
        for key, payload in routes.items():
            if key in url:
                raw = json.dumps(payload).encode("utf-8")
                return Resp(raw)
        raise URLError(f"unmocked url: {url}")

    return opener


class BinanceTHTapeTests(unittest.TestCase):
    def test_fixture_ticker(self):
        row = bnth_tape.fetch_public_ticker("BTCTHB", use_fixture=True)
        self.assertEqual(row["symbol"], "BTCTHB")
        q = bnth_tape.ticker_to_tape_quote(row)
        self.assertEqual(q.venue, "binance_th")
        self.assertGreater(q.price, 0)
        self.assertEqual(q.source, "binance_th_ticker_price")

    def test_fetch_price_mocked_th_host_only(self):
        routes = {
            "ticker/price": {"symbol": "BTCTHB", "price": "2500000.50"},
            "ticker/bookTicker": {
                "symbol": "BTCTHB",
                "bidPrice": "2499900.00",
                "askPrice": "2500100.00",
                "bidQty": "0.1",
                "askQty": "0.1",
            },
        }
        with mock.patch(
            "venues.binance_th.tape.urllib.request.urlopen",
            side_effect=_route_urlopen(routes),
        ):
            row = bnth_tape.fetch_public_ticker("BTCTHB", timeout=1.0, use_fixture=False)
        self.assertAlmostEqual(float(row["price"]), 2500000.50)
        self.assertEqual(row["_source_host"], "api.binance.th")
        self.assertIn("bidPrice", row)

    def test_symbol_normalize(self):
        self.assertEqual(bnth_tape._normalize_symbol("BTC_THB"), "BTCTHB")
        self.assertEqual(bnth_tape._normalize_symbol("btc-thb"), "BTCTHB")

    def test_refuse_non_th_host(self):
        with self.assertRaises(bnth_tape.BinanceTHError) as cm:
            bnth_tape._assert_th_host("https://api.binance.com/api/v3/ticker/price")
        self.assertIn("binance.com", str(cm.exception).lower())

    def test_network_error(self):
        with mock.patch(
            "venues.binance_th.tape.urllib.request.urlopen",
            side_effect=URLError("down"),
        ):
            with self.assertRaises(bnth_tape.BinanceTHError) as cm:
                bnth_tape.fetch_public_ticker("BTCTHB", timeout=1.0, use_fixture=False)
        self.assertIn("network error", str(cm.exception).lower())

    def test_paper_fill_buy_ask(self):
        row = {
            "symbol": "BTCTHB",
            "lastPrice": 2500000.0,
            "askPrice": 2500100.0,
            "bidPrice": 2499900.0,
        }
        fill = bnth_paper.paper_fill_from_ticker(row, side="buy", stake_thb=100.0)
        self.assertEqual(fill["venue"], "binance_th_paper")
        self.assertFalse(fill["live"])
        self.assertEqual(fill["price_source"], "ask")
        self.assertAlmostEqual(fill["px"], 2500100.0)

    def test_refuse_live(self):
        with self.assertRaises(bnth_tape.BinanceTHError):
            bnth_paper.refuse_live()


class DexCexArbTests(unittest.TestCase):
    def test_same_currency_opportunity_net_positive(self):
        dex = {"venue": "oneinch", "symbol": "WBTC-USD", "price": 100.0, "ts": "t", "source": "fixture"}
        cex = {"venue": "binance_th", "symbol": "BTCUSDT", "price": 101.0, "ts": "t", "source": "fixture"}
        fees = ArbFeeConfig(
            dex_fee_bps=10,
            cex_fee_bps=10,
            withdraw_fee_bps=0,
            transfer_time_penalty_bps=5,
            travel_rule_buffer_bps=5,
        )
        # gross buy_dex_sell_cex = 100 bps; cost = 30; net = 70
        out = detect_dex_cex_opportunity(dex, cex, fees=fees)
        self.assertFalse(out["kill"])
        self.assertEqual(out["status"], "opportunity")
        self.assertAlmostEqual(out["gross_spread_bps"], 100.0, places=4)
        self.assertAlmostEqual(out["net_edge_bps"], 70.0, places=4)
        self.assertIn("gross_vs_net", out)
        self.assertEqual(out["transfer_time_penalty_bps"], 5)
        self.assertEqual(out["travel_rule_buffer_bps"], 5)

    def test_kill_when_net_non_positive(self):
        dex = {"venue": "oneinch", "symbol": "WBTC-USD", "price": 100.0, "ts": "t", "source": "f"}
        cex = {"venue": "binance_th", "symbol": "BTCUSDT", "price": 100.1, "ts": "t", "source": "f"}
        fees = ArbFeeConfig(
            dex_fee_bps=30,
            cex_fee_bps=10,
            withdraw_fee_bps=5,
            transfer_time_penalty_bps=15,
            travel_rule_buffer_bps=10,
        )
        # gross ~10 bps; cost 70 → kill
        out = detect_dex_cex_opportunity(dex, cex, fees=fees)
        self.assertTrue(out["kill"])
        self.assertEqual(out["kill_reason"], "net_edge_bps<=0")
        self.assertEqual(out["status"], "no_edge")

    def test_unit_mismatch_kills_without_fx(self):
        dex = {"venue": "oneinch", "symbol": "WBTC-USD", "price": 95000.0, "ts": "t", "source": "f"}
        cex = {"venue": "binance_th", "symbol": "BTCTHB", "price": 2600000.0, "ts": "t", "source": "f"}
        out = detect_dex_cex_opportunity(dex, cex)
        self.assertTrue(out["kill"])
        self.assertEqual(out["status"], "unit_mismatch")
        self.assertEqual(out["kill_reason"], "unit_mismatch")

    def test_fx_adjusted_with_labeled_usdthb(self):
        dex = {"venue": "oneinch", "symbol": "WBTC-USD", "price": 100000.0, "ts": "t", "source": "f"}
        cex = {"venue": "binance_th", "symbol": "BTCTHB", "price": 3_600_000.0, "ts": "t", "source": "f"}
        usdthb = {"price": 36.0, "source": "test_labeled", "ts": "t"}
        fees = ArbFeeConfig(
            dex_fee_bps=5,
            cex_fee_bps=5,
            withdraw_fee_bps=0,
            transfer_time_penalty_bps=5,
            travel_rule_buffer_bps=5,
        )
        # cex USD-eq = 3600000/36 = 100000; flat → gross 0 → kill
        out = detect_dex_cex_opportunity(dex, cex, fees=fees, usdthb=usdthb)
        self.assertTrue(out["comparable"])
        self.assertEqual(out["unit"], "USD_equivalent")
        # make CEX rich: 3_636_000 / 36 = 101000 → ~100 bps
        cex2 = dict(cex, price=3_636_000.0)
        out2 = detect_dex_cex_opportunity(dex, cex2, fees=fees, usdthb=usdthb)
        self.assertFalse(out2["kill"])
        self.assertGreater(out2["net_edge_bps"], 0)

    def test_fee_stack_includes_non_zero_latency_and_travel_rule(self):
        fees = ArbFeeConfig()
        self.assertGreater(fees.transfer_time_penalty_bps, 0)
        self.assertGreater(fees.travel_rule_buffer_bps, 0)
        d = fees.to_dict()
        self.assertIn("estimate", d["note"].lower())

    def test_paper_dual_leg_tags(self):
        dex = {"venue": "oneinch", "symbol": "WBTC-USD", "price": 100.0, "ts": "t", "source": "f"}
        cex = {"venue": "binance_th", "symbol": "BTCUSDT", "price": 102.0, "ts": "t", "source": "f"}
        fees = ArbFeeConfig(
            dex_fee_bps=5, cex_fee_bps=5, withdraw_fee_bps=0,
            transfer_time_penalty_bps=5, travel_rule_buffer_bps=5,
        )
        opp = detect_dex_cex_opportunity(dex, cex, fees=fees)
        sim = simulate_paper_dual_leg(opp, size=0.01)
        self.assertTrue(sim["ok"])
        self.assertEqual(sim["dex"]["venue"], "dex_paper")
        self.assertEqual(sim["cex"]["venue"], "binance_th_paper")
        self.assertFalse(sim["live"])


class ArbScanCliTests(unittest.TestCase):
    def test_live_hard_refuse(self):
        rc = pmm_arb_scan.main(["--live"])
        self.assertEqual(rc, 2)

    def test_fixture_scan_with_usdthb(self):
        # Capture stdout
        import io as _io
        from contextlib import redirect_stdout

        buf = _io.StringIO()
        with redirect_stdout(buf):
            rc = pmm_arb_scan.main(
                [
                    "--paper",
                    "--fixture",
                    "--cex",
                    "binance_th",
                    "--usdthb",
                    "36.0",
                    "--usdthb-source",
                    "test",
                    "--transfer-time-penalty-bps",
                    "15",
                    "--travel-rule-buffer-bps",
                    "10",
                ]
            )
        self.assertEqual(rc, 0)
        data = json.loads(buf.getvalue())
        self.assertTrue(data["ok"])
        self.assertFalse(data["live"])
        self.assertIn("opportunity", data)
        opp = data["opportunity"]
        self.assertIn("gross_vs_net", opp)
        self.assertEqual(opp["transfer_time_penalty_bps"], 15)
        self.assertEqual(opp["travel_rule_buffer_bps"], 10)


if __name__ == "__main__":
    unittest.main()
