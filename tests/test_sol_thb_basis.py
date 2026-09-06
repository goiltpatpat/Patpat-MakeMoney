#!/usr/bin/env python3
"""Unit tests for SOL–THB basis (Bitkub+BNTH vs Jupiter×labeled FX; mocked HTTP)."""
from __future__ import annotations

import io
import json
import sys
import unittest
from datetime import datetime, timedelta, timezone
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

from venues.basis.sol_thb import (  # noqa: E402
    SolThbFeeConfig,
    detect_jupiter_vs_cex_thb,
    detect_same_ccy_sol_thb,
    jupiter_to_thb_equiv,
    scan_sol_thb_basis,
)
import pmm_sol_basis_scan  # noqa: E402


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class SameCcySolTests(unittest.TestCase):
    def test_same_ccy_net_after_fees(self):
        now = _now()
        bitkub = {
            "venue": "bitkub_public",
            "symbol": "SOL_THB",
            "price": 5400.0,
            "ts": now,
            "source": "bitkub_v3_market_ticker",
        }
        bnth = {
            "venue": "binance_th",
            "symbol": "SOLTHB",
            "price": 5430.0,
            "ts": now,
            "source": "binance_th_ticker_price",
        }
        fees = SolThbFeeConfig(bitkub_taker_bps=10.0, bnth_taker_bps=10.0)
        out = detect_same_ccy_sol_thb(bitkub, bnth, fees=fees, allow_fixture=False)
        self.assertFalse(out["kill"])
        self.assertEqual(out["unit"], "THB")
        self.assertEqual(out["lane"], "same_ccy")
        self.assertEqual(out["direction"], "bnth_rich")
        self.assertEqual(out["net_basis_bps_label"], "ESTIMATE")
        self.assertAlmostEqual(out["fee_floor_bps"], 20.0)
        self.assertAlmostEqual(
            out["net_basis_bps"], abs(out["gross_basis_bps"]) - 20.0, places=5
        )

    def test_unit_mismatch_kill(self):
        now = _now()
        bitkub = {
            "venue": "bitkub_public",
            "symbol": "SOL_THB",
            "price": 5400.0,
            "ts": now,
            "source": "bitkub_v3",
        }
        bnth = {
            "venue": "binance_th",
            "symbol": "SOLUSDT",
            "price": 150.0,
            "ts": now,
            "source": "binance_th_ticker_price",
        }
        out = detect_same_ccy_sol_thb(bitkub, bnth)
        self.assertTrue(out["kill"])
        self.assertEqual(out["kill_reason"], "unit_mismatch")

    def test_fixture_kill_unless_allowed(self):
        now = _now()
        bitkub = {
            "venue": "bitkub_public",
            "symbol": "SOL_THB",
            "price": 5400.0,
            "ts": now,
            "source": "fixture",
        }
        bnth = {
            "venue": "binance_th",
            "symbol": "SOLTHB",
            "price": 5410.0,
            "ts": now,
            "source": "fixture",
        }
        killed = detect_same_ccy_sol_thb(bitkub, bnth, allow_fixture=False)
        self.assertTrue(killed["kill"])
        self.assertEqual(killed["kill_reason"], "money_leg_source_fixture")
        allowed = detect_same_ccy_sol_thb(bitkub, bnth, allow_fixture=True)
        self.assertFalse(allowed["kill"])

    def test_stale_kill(self):
        old = (datetime.now(timezone.utc) - timedelta(seconds=120)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        bitkub = {
            "venue": "bitkub_public",
            "symbol": "SOL_THB",
            "price": 5400.0,
            "ts": old,
            "source": "bitkub_v3",
        }
        bnth = {
            "venue": "binance_th",
            "symbol": "SOLTHB",
            "price": 5410.0,
            "ts": old,
            "source": "binance_th_ticker_price",
        }
        out = detect_same_ccy_sol_thb(bitkub, bnth, max_age_sec=30.0)
        self.assertTrue(out["kill"])
        self.assertEqual(out["kill_reason"], "stale")


class JupiterFxTests(unittest.TestCase):
    def test_jupiter_to_thb_equiv(self):
        jup = {
            "venue": "jupiter_solana",
            "symbol": "SOL/USDC",
            "price": 150.0,
            "ts": _now(),
            "source": "jupiter_swap_v2_order",
        }
        fx = {
            "price": 36.0,
            "pair": "USDTTHB",
            "source": "binance_th_usdtthb",
            "ts": _now(),
        }
        eq = jupiter_to_thb_equiv(jup, fx)
        self.assertAlmostEqual(eq["price"], 5400.0)
        self.assertEqual(eq["quote_ccy"], "THB")
        self.assertIn("USDC≈USDT", eq["components"]["stable_label"])

    def test_jupiter_vs_cex_net_estimate(self):
        now = _now()
        cex = {
            "venue": "binance_th",
            "symbol": "SOLTHB",
            "price": 5400.0,
            "ts": now,
            "source": "binance_th_ticker_price",
        }
        jup_eq = {
            "venue": "jupiter_thb_equiv",
            "symbol": "SOL_THB_equiv",
            "price": 5454.0,  # ~100 bps richer
            "ts": now,
            "source": "jupiter_usdc_x_bnth_usdtthb",
        }
        fx = {
            "price": 36.0,
            "pair": "USDTTHB",
            "source": "binance_th_usdtthb",
            "ts": now,
        }
        fees = SolThbFeeConfig(
            bnth_taker_bps=10.0, jupiter_fee_bps=5.0, fx_slip_bps=2.0
        )
        out = detect_jupiter_vs_cex_thb(cex, jup_eq, fx, fees=fees)
        self.assertFalse(out["kill"])
        self.assertEqual(out["lane"], "jupiter_fx")
        self.assertEqual(out["direction"], "jupiter_rich")
        self.assertEqual(out["net_basis_bps_label"], "ESTIMATE")
        self.assertAlmostEqual(out["fee_floor_bps"], 17.0)
        self.assertIn("USDTTHB", out["fx_label"])

    def test_jupiter_fixture_kill(self):
        now = _now()
        cex = {
            "venue": "binance_th",
            "symbol": "SOLTHB",
            "price": 5400.0,
            "ts": now,
            "source": "fixture",
        }
        jup_eq = {
            "venue": "jupiter_thb_equiv",
            "symbol": "SOL_THB_equiv",
            "price": 5410.0,
            "ts": now,
            "source": "fixture",
            "fixture": True,
        }
        fx = {
            "price": 36.0,
            "pair": "USDTTHB",
            "source": "fixture",
            "ts": now,
            "fixture": True,
        }
        out = detect_jupiter_vs_cex_thb(cex, jup_eq, fx, allow_fixture=False)
        self.assertTrue(out["kill"])
        self.assertEqual(out["kill_reason"], "money_leg_source_fixture")


class ScanFixtureTests(unittest.TestCase):
    def test_scan_fixture_killed_by_default(self):
        out = scan_sol_thb_basis(use_fixture=True, allow_fixture=False, include_jupiter=True)
        self.assertTrue(out["kill"])
        same = out["same_ccy"]
        self.assertTrue(same["kill"])
        self.assertEqual(same["kill_reason"], "money_leg_source_fixture")

    def test_scan_fixture_allowed(self):
        out = scan_sol_thb_basis(use_fixture=True, allow_fixture=True, include_jupiter=True)
        self.assertFalse(out["kill"])
        self.assertEqual(out["same_ccy"]["unit"], "THB")
        self.assertEqual(out["jupiter_fx"]["unit"], "THB")
        self.assertEqual(out["estimated_fees"]["label"], "ESTIMATE")

    def test_scan_fetch_failed_no_invent(self):
        with mock.patch(
            "venues.bitkub.paper.urllib.request.urlopen",
            side_effect=URLError("down"),
        ), mock.patch(
            "venues.binance_th.tape.urllib.request.urlopen",
            side_effect=URLError("down"),
        ), mock.patch(
            "venues.solana.jupiter_quotes.urllib.request.urlopen",
            side_effect=URLError("down"),
        ):
            out = scan_sol_thb_basis(use_fixture=False, allow_fixture=False, timeout=1.0)
        self.assertTrue(out["kill"])
        self.assertEqual(out["same_ccy"]["kill_reason"], "fetch_failed")
        self.assertIsNone(out["same_ccy"]["legs"]["bitkub"])


class CliTests(unittest.TestCase):
    def test_live_refuse(self):
        buf = io.StringIO()
        with mock.patch("sys.stdout", buf):
            rc = pmm_sol_basis_scan.main(["--live"])
        self.assertEqual(rc, 2)
        data = json.loads(buf.getvalue())
        self.assertIn("REFUSED", data["error"])
        self.assertFalse(data["live"])

    def test_fixture_allow_cli(self):
        buf = io.StringIO()
        with mock.patch("sys.stdout", buf):
            rc = pmm_sol_basis_scan.main(
                ["--paper", "--fixture", "--allow-fixture", "--prices-only"]
            )
        self.assertEqual(rc, 0)
        data = json.loads(buf.getvalue())
        self.assertEqual(data["asset"], "SOL")
        self.assertIn("same_ccy_gross_bps", data)
        self.assertIn("jupiter_fx_net_bps", data)
        self.assertEqual(data["same_ccy_net_label"], "ESTIMATE")


if __name__ == "__main__":
    unittest.main()
