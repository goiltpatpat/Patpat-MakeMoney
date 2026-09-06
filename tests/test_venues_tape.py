#!/usr/bin/env python3
"""Unit tests for multi-venue tape (mocked HTTP — no live network required)."""
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
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from venues import TapeQuote  # noqa: E402
from venues import oneinch_quotes, public_btc  # noqa: E402
from venues.bitkub import paper as bitkub_paper  # noqa: E402


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


class TapeQuoteTests(unittest.TestCase):
    def test_tape_quote_dict(self):
        q = TapeQuote(
            venue="binance_public",
            symbol="BTCUSDT",
            price=100.0,
            ts="2026-09-06T00:00:00Z",
            source="test",
        )
        d = q.to_dict()
        self.assertEqual(d["venue"], "binance_public")
        self.assertEqual(d["price"], 100.0)


class PublicBtcTests(unittest.TestCase):
    def test_fetch_last_ok(self):
        with mock.patch(
            "venues.public_btc.urllib.request.urlopen",
            side_effect=_fake_urlopen({"symbol": "BTCUSDT", "price": "65000.5"}),
        ):
            q = public_btc.fetch_btc_usdt_last(timeout=1.0)
        self.assertEqual(q.symbol, "BTCUSDT")
        self.assertAlmostEqual(q.price, 65000.5)
        self.assertEqual(q.source, "binance_ticker_price")

    def test_fetch_mark_ok(self):
        with mock.patch(
            "venues.public_btc.urllib.request.urlopen",
            side_effect=_fake_urlopen({"symbol": "BTCUSDT", "markPrice": "65100.0"}),
        ):
            q = public_btc.fetch_btc_usdt_mark(timeout=1.0)
        self.assertAlmostEqual(q.price, 65100.0)
        self.assertEqual(q.source, "binance_premium_index_mark")

    def test_network_error_clear(self):
        with mock.patch(
            "venues.public_btc.urllib.request.urlopen",
            side_effect=URLError("down"),
        ):
            with self.assertRaises(public_btc.PublicBtcError) as cm:
                public_btc.fetch_btc_usdt_last(timeout=1.0)
        self.assertIn("network error", str(cm.exception).lower())

    def test_bad_payload(self):
        with mock.patch(
            "venues.public_btc.urllib.request.urlopen",
            side_effect=_fake_urlopen({"symbol": "BTCUSDT"}),
        ):
            with self.assertRaises(public_btc.PublicBtcError):
                public_btc.fetch_btc_usdt_last(timeout=1.0)


class OneInchTests(unittest.TestCase):
    def test_fixture_without_key(self):
        with mock.patch.dict("os.environ", {}, clear=False):
            # ensure key absent
            env = {k: v for k, v in dict(**__import__("os").environ).items() if k != "ONEINCH_API_KEY"}
            with mock.patch.dict("os.environ", env, clear=True):
                q = oneinch_quotes.fetch_wbtc_usd_quote(allow_fixture=True)
        self.assertEqual(q.source, "fixture")
        self.assertEqual(q.venue, "oneinch")
        self.assertGreater(q.price, 0)

    def test_live_price_with_key_mocked(self):
        payload = {oneinch_quotes.WBTC_ETH.lower(): "94000.25"}
        with mock.patch(
            "venues.oneinch_quotes.urllib.request.urlopen",
            side_effect=_fake_urlopen(payload),
        ):
            q = oneinch_quotes.fetch_wbtc_usd_quote(api_key="test-key", allow_fixture=False, timeout=1.0)
        self.assertAlmostEqual(q.price, 94000.25)
        self.assertEqual(q.source, "oneinch_spot_price_v1.1")

    def test_no_key_no_fixture_raises(self):
        with mock.patch.dict("os.environ", {"ONEINCH_API_KEY": ""}, clear=False):
            with self.assertRaises(oneinch_quotes.OneInchQuoteError):
                oneinch_quotes.fetch_wbtc_usd_quote(api_key="", allow_fixture=False)


class BitkubPaperTests(unittest.TestCase):
    SAMPLE = {
        "symbol": "BTC_THB",
        "last": "2500000.0",
        "lowest_ask": "2500100.0",
        "highest_bid": "2499900.0",
    }

    def test_ticker_parse_list(self):
        with mock.patch(
            "venues.bitkub.paper.urllib.request.urlopen",
            side_effect=_fake_urlopen([self.SAMPLE]),
        ):
            row = bitkub_paper.fetch_public_ticker("BTC_THB", timeout=1.0)
        self.assertEqual(float(row["last"]), 2500000.0)

    def test_paper_fill_buy_uses_ask(self):
        fill = bitkub_paper.paper_fill_from_ticker(self.SAMPLE, side="buy", symbol="BTC_THB")
        self.assertEqual(fill["mode"], "paper")
        self.assertFalse(fill["live"])
        self.assertEqual(fill["price_source"], "ask")
        self.assertAlmostEqual(fill["fill_price"], 2500100.0)

    def test_paper_fill_sell_uses_bid(self):
        fill = bitkub_paper.paper_fill_from_ticker(self.SAMPLE, side="sell", symbol="BTC_THB")
        self.assertEqual(fill["price_source"], "bid")
        self.assertAlmostEqual(fill["fill_price"], 2499900.0)

    def test_simulate_paper_with_row(self):
        out = bitkub_paper.simulate_paper_order(side="buy", ticker_row=self.SAMPLE)
        self.assertIn("tape", out)
        self.assertEqual(out["tape"]["venue"], "bitkub_public")

    def test_live_stub_raises(self):
        with self.assertRaises(bitkub_paper.BitkubPaperError):
            bitkub_paper.live_order_stub()


class DoctorVenuesPresenceTests(unittest.TestCase):
    def test_venues_files_exist(self):
        for rel in (
            "docs/VENUES.md",
            "src/venues/__init__.py",
            "src/venues/public_btc.py",
            "src/venues/oneinch_quotes.py",
            "src/venues/bitkub/paper.py",
            "scripts/pmm_tape.py",
        ):
            self.assertTrue((ROOT / rel).exists(), msg=rel)


if __name__ == "__main__":
    unittest.main()
