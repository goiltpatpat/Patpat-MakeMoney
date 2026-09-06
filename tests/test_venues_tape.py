#!/usr/bin/env python3
"""Unit tests for multi-venue tape + Bitkub paper round-trip (mocked HTTP)."""
from __future__ import annotations

import io
import json
import sys
import tempfile
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
        fill = bitkub_paper.paper_fill_from_ticker(
            self.SAMPLE, side="buy", symbol="BTC_THB", stake_thb=100.0
        )
        self.assertEqual(fill["mode"], "paper")
        self.assertFalse(fill["live"])
        self.assertEqual(fill["price_source"], "ask")
        self.assertAlmostEqual(fill["px"], 2500100.0)
        self.assertIsNotNone(fill["size"])
        self.assertIsNotNone(fill["fee_estimate"])
        self.assertGreater(fill["fee_estimate"], 0)

    def test_paper_fill_sell_uses_bid(self):
        fill = bitkub_paper.paper_fill_from_ticker(
            self.SAMPLE, side="sell", symbol="BTC_THB", size=0.0001
        )
        self.assertEqual(fill["price_source"], "bid")
        self.assertAlmostEqual(fill["px"], 2499900.0)

    def test_simulate_paper_with_row(self):
        out = bitkub_paper.simulate_paper_order(side="buy", ticker_row=self.SAMPLE)
        self.assertIn("tape", out)
        self.assertEqual(out["tape"]["venue"], "bitkub_public")

    def test_live_stub_raises(self):
        with self.assertRaises(bitkub_paper.BitkubPaperError):
            bitkub_paper.live_order_stub()

    def test_refuse_live_raises(self):
        with self.assertRaises(bitkub_paper.BitkubPaperError) as cm:
            bitkub_paper.refuse_live()
        self.assertIn("not implemented", str(cm.exception).lower())

    def test_round_trip_parseable_fills(self):
        with tempfile.TemporaryDirectory() as td:
            rt = Path(td)
            out = bitkub_paper.paper_round_trip(
                stake_thb=100.0,
                open_row=self.SAMPLE,
                close_row=self.SAMPLE,
                runtime_dir=rt,
                enforce_caps=True,
                record=True,
            )
        self.assertTrue(out["ok"])
        self.assertFalse(out["live"])
        for leg in ("open", "close"):
            f = out[leg]
            for key in ("side", "size", "px", "fee_estimate", "ts"):
                self.assertIn(key, f, msg=key)
            self.assertIsNotNone(f["size"])
            self.assertIsNotNone(f["fee_estimate"])
        self.assertEqual(out["open"]["side"], "buy")
        self.assertEqual(out["close"]["side"], "sell")
        self.assertAlmostEqual(out["open"]["size"], out["close"]["size"])
        # Same-tick ask>bid ⇒ negative paper PnL after fees (from fills, not invented)
        self.assertLess(out["realized_pnl_thb"], 0)
        self.assertIn("paper fills only", out["pnl_basis"])

    def test_day_cap_blocks(self):
        with tempfile.TemporaryDirectory() as td:
            rt = Path(td)
            caps = {
                "max_trades_per_day": 1,
                "max_loss_thb": 500.0,
                "fee_rate": 0.0025,
            }
            (rt / bitkub_paper.CAPS_FILENAME).write_text(json.dumps(caps), encoding="utf-8")
            bitkub_paper.paper_round_trip(
                stake_thb=50.0,
                open_row=self.SAMPLE,
                close_row=self.SAMPLE,
                runtime_dir=rt,
                enforce_caps=True,
                record=True,
            )
            with self.assertRaises(bitkub_paper.BitkubPaperError) as cm:
                bitkub_paper.paper_round_trip(
                    stake_thb=50.0,
                    open_row=self.SAMPLE,
                    close_row=self.SAMPLE,
                    runtime_dir=rt,
                    enforce_caps=True,
                    record=True,
                )
            msg = str(cm.exception).lower()
            self.assertTrue("cap" in msg or "stop" in msg, msg=msg)


class EdgeLogTests(unittest.TestCase):
    def test_append_round_trip(self):
        sys.path.insert(0, str(ROOT / "scripts"))
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "pmm_edge_log", ROOT / "scripts" / "pmm_edge_log.py"
        )
        mod = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(mod)

        payload = {
            "live": False,
            "venue": "bitkub",
            "symbol": "BTC_THB",
            "round_trip_id": "t1",
            "realized_pnl_thb": -1.5,
            "pnl_basis": "paper fills only",
            "open": {
                "venue": "bitkub",
                "side": "buy",
                "size": 0.0001,
                "px": 100.0,
                "fee_estimate": 0.01,
                "ts": "2026-09-06T00:00:00Z",
                "leg": "open",
                "live": False,
            },
            "close": {
                "venue": "bitkub",
                "side": "sell",
                "size": 0.0001,
                "px": 99.0,
                "fee_estimate": 0.01,
                "ts": "2026-09-06T00:00:01Z",
                "leg": "close",
                "live": False,
            },
        }
        with tempfile.TemporaryDirectory() as td:
            log = Path(td) / "edge_log.jsonl"
            out = mod.append_edge_log(payload, log_path=log)
            self.assertEqual(out["written"], 2)
            lines = log.read_text(encoding="utf-8").strip().splitlines()
            self.assertEqual(len(lines), 2)
            close_rec = json.loads(lines[1])
            self.assertEqual(close_rec["realized_pnl_thb"], -1.5)

    def test_refuse_live_payload(self):
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "pmm_edge_log2", ROOT / "scripts" / "pmm_edge_log.py"
        )
        mod = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(mod)
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(ValueError):
                mod.append_edge_log({"live": True, "fill": {"side": "buy"}}, log_path=Path(td) / "e.jsonl")


class DoctorVenuesPresenceTests(unittest.TestCase):
    def test_venues_files_exist(self):
        for rel in (
            "docs/VENUES.md",
            "src/venues/__init__.py",
            "src/venues/public_btc.py",
            "src/venues/oneinch_quotes.py",
            "src/venues/bitkub/paper.py",
            "scripts/pmm_tape.py",
            "scripts/pmm_bitkub_paper.py",
            "scripts/pmm_edge_log.py",
        ):
            self.assertTrue((ROOT / rel).exists(), msg=rel)


if __name__ == "__main__":
    unittest.main()
