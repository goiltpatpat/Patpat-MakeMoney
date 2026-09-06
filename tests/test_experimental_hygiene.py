#!/usr/bin/env python3
"""Hygiene tests: fixture-kill, utf-8-sig day caps, allow-fixture CLI."""
from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

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
)
from venues.bitkub import paper as bitkub_paper  # noqa: E402
from venues.binance_th import tape as bnth_tape  # noqa: E402
import pmm_arb_scan  # noqa: E402


class FixtureKillTests(unittest.TestCase):
    def _fat_fees(self) -> ArbFeeConfig:
        return ArbFeeConfig(
            dex_fee_bps=5,
            cex_fee_bps=5,
            withdraw_fee_bps=0,
            transfer_time_penalty_bps=5,
            travel_rule_buffer_bps=5,
        )

    def test_fixture_dex_killed_by_default(self):
        dex = {"venue": "oneinch", "symbol": "WBTC-USD", "price": 100.0, "ts": "t", "source": "fixture"}
        cex = {
            "venue": "binance_th",
            "symbol": "BTCUSDT",
            "price": 110.0,
            "ts": "t",
            "source": "binance_th_ticker_price",
        }
        out = detect_dex_cex_opportunity(dex, cex, fees=self._fat_fees())
        self.assertTrue(out["kill"])
        self.assertEqual(out["kill_reason"], "money_leg_source_fixture")
        self.assertEqual(out["status"], "fixture_mid")
        # Must not claim positive net from fixture on money path
        self.assertTrue(out.get("net_edge_bps") in (None, 0) or out["kill"])

    def test_fixture_cex_killed_by_default(self):
        dex = {
            "venue": "oneinch",
            "symbol": "WBTC-USD",
            "price": 100.0,
            "ts": "t",
            "source": "oneinch_spot_price_v1.1",
        }
        cex = {"venue": "binance_th", "symbol": "BTCUSDT", "price": 110.0, "ts": "t", "source": "fixture"}
        out = detect_dex_cex_opportunity(dex, cex, fees=self._fat_fees())
        self.assertTrue(out["kill"])
        self.assertEqual(out["kill_reason"], "money_leg_source_fixture")

    def test_allow_fixture_permits_offline_edge(self):
        dex = {"venue": "oneinch", "symbol": "WBTC-USD", "price": 100.0, "ts": "t", "source": "fixture"}
        cex = {"venue": "binance_th", "symbol": "BTCUSDT", "price": 101.0, "ts": "t", "source": "fixture"}
        out = detect_dex_cex_opportunity(dex, cex, fees=self._fat_fees(), allow_fixture=True)
        self.assertFalse(out["kill"])
        self.assertEqual(out["status"], "opportunity")
        self.assertGreater(out["net_edge_bps"], 0)

    def test_non_fixture_sources_still_score(self):
        dex = {"venue": "oneinch", "symbol": "WBTC-USD", "price": 100.0, "ts": "t", "source": "live_mock"}
        cex = {"venue": "binance_th", "symbol": "BTCUSDT", "price": 101.0, "ts": "t", "source": "live_mock"}
        out = detect_dex_cex_opportunity(dex, cex, fees=self._fat_fees())
        self.assertFalse(out["kill"])
        self.assertGreater(out["net_edge_bps"], 0)


class Utf8SigCapsTests(unittest.TestCase):
    def test_load_day_caps_with_bom(self):
        with tempfile.TemporaryDirectory() as td:
            rt = Path(td)
            caps = {
                "max_trades_per_day": 3,
                "max_loss_thb": 100.0,
                "fee_rate": 0.0025,
            }
            raw = json.dumps(caps, indent=2) + "\n"
            # PowerShell-style UTF-8 with BOM
            (rt / bitkub_paper.CAPS_FILENAME).write_bytes(b"\xef\xbb\xbf" + raw.encode("utf-8"))
            loaded = bitkub_paper.load_day_caps(rt)
            self.assertEqual(int(loaded["max_trades_per_day"]), 3)
            self.assertAlmostEqual(float(loaded["max_loss_thb"]), 100.0)


class BnthUsdtthbHelperTests(unittest.TestCase):
    def test_fixture_fx_labeled(self):
        fx = bnth_tape.fetch_usdtthb_fx(use_fixture=True)
        self.assertEqual(fx["pair"], "USDTTHB")
        self.assertEqual(fx["source"], "fixture")
        self.assertGreater(fx["price"], 0)
        self.assertIn("api.binance.th", fx["host"])

    def test_bnth_fixture_quote_source(self):
        row = bnth_tape.fetch_public_ticker("BTCTHB", use_fixture=True)
        q = bnth_tape.ticker_to_tape_quote(row)
        self.assertEqual(q.source, "fixture")


class ArbScanAllowFixtureCliTests(unittest.TestCase):
    def test_fixture_without_allow_kills(self):
        buf = io.StringIO()
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
                    "--no-fetch-usdthb",
                ]
            )
        self.assertEqual(rc, 0)
        data = json.loads(buf.getvalue())
        opp = data["opportunity"]
        self.assertTrue(opp["kill"])
        self.assertEqual(opp["kill_reason"], "money_leg_source_fixture")
        self.assertFalse(data.get("allow_fixture"))

    def test_fixture_with_allow_runs(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = pmm_arb_scan.main(
                [
                    "--paper",
                    "--fixture",
                    "--allow-fixture",
                    "--cex",
                    "binance_th",
                    "--usdthb",
                    "36.0",
                    "--usdthb-source",
                    "test",
                    "--no-fetch-usdthb",
                ]
            )
        self.assertEqual(rc, 0)
        data = json.loads(buf.getvalue())
        self.assertTrue(data["ok"])
        self.assertTrue(data["allow_fixture"])
        opp = data["opportunity"]
        self.assertIn("gross_vs_net", opp)
        # With allow_fixture, may be opportunity or no_edge depending on fee stack — but not fixture kill
        self.assertNotEqual(opp.get("kill_reason"), "money_leg_source_fixture")


class DoctorApisPresenceTests(unittest.TestCase):
    def test_apis_and_holes_exist(self):
        self.assertTrue((ROOT / "docs/APIS.md").exists())
        self.assertTrue((ROOT / "docs/HOLES.md").exists())
        apis = (ROOT / "docs/APIS.md").read_text(encoding="utf-8")
        self.assertIn("api.binance.th", apis)
        self.assertIn("ONEINCH_API_KEY", apis)
        self.assertIn("Travel Rule", apis)


if __name__ == "__main__":
    unittest.main()
