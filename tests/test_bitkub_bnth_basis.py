#!/usr/bin/env python3
"""Unit tests for Bitkub↔BNTH same-ccy THB basis monitor (mocked HTTP)."""
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

from venues.basis.bitkub_bnth import (  # noqa: E402
    BasisFeeConfig,
    compute_basis_bps,
    detect_bitkub_bnth_basis,
    opportunity_persisted,
    scan_bitkub_bnth_basis,
)
import pmm_basis_scan  # noqa: E402


def _route_urlopen(routes: dict):
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
                if isinstance(payload, Exception):
                    raise payload
                raw = json.dumps(payload).encode("utf-8")
                return Resp(raw)
        raise URLError(f"unmocked url: {url}")

    return opener


class ComputeBasisTests(unittest.TestCase):
    def test_sign_convention_bnth_rich(self):
        # bnth > bitkub → positive
        calc = compute_basis_bps(2_000_000.0, 2_001_000.0)
        self.assertGreater(calc["basis_bps"], 0)
        mid = (2_000_000.0 + 2_001_000.0) / 2.0
        expected = (1000.0 / mid) * 1e4
        self.assertAlmostEqual(calc["gross_basis_bps"], expected, places=6)

    def test_sign_convention_bitkub_rich(self):
        calc = compute_basis_bps(2_001_000.0, 2_000_000.0)
        self.assertLess(calc["basis_bps"], 0)


class DetectBasisTests(unittest.TestCase):
    def test_same_ccy_net_after_fees(self):
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        bitkub = {
            "venue": "bitkub_public",
            "symbol": "BTC_THB",
            "price": 2_000_000.0,
            "ts": now,
            "source": "bitkub_v3_market_ticker",
        }
        # ~50 bps gross when mid ~2e6 and delta 10_000
        bnth = {
            "venue": "binance_th",
            "symbol": "BTCTHB",
            "price": 2_010_000.0,
            "ts": now,
            "source": "binance_th_ticker_price",
        }
        fees = BasisFeeConfig(bitkub_taker_bps=10.0, bnth_taker_bps=10.0, min_net_bps=0.0)
        out = detect_bitkub_bnth_basis(bitkub, bnth, fees=fees, allow_fixture=False)
        self.assertFalse(out["kill"])
        self.assertEqual(out["unit"], "THB")
        self.assertEqual(out["direction"], "bnth_rich")
        self.assertAlmostEqual(out["fee_floor_bps"], 20.0)
        self.assertGreater(out["gross_basis_bps"], 0)
        self.assertAlmostEqual(
            out["net_basis_bps"], abs(out["gross_basis_bps"]) - 20.0, places=5
        )
        self.assertTrue(out["opportunity"])

    def test_unit_mismatch_kill(self):
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        bitkub = {
            "venue": "bitkub_public",
            "symbol": "BTC_THB",
            "price": 2_000_000.0,
            "ts": now,
            "source": "bitkub_v3",
        }
        bnth = {
            "venue": "binance_th",
            "symbol": "BTCUSDT",
            "price": 60_000.0,
            "ts": now,
            "source": "binance_th_ticker_price",
        }
        out = detect_bitkub_bnth_basis(bitkub, bnth)
        self.assertTrue(out["kill"])
        self.assertEqual(out["kill_reason"], "unit_mismatch")

    def test_fixture_kill_unless_allowed(self):
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        bitkub = {
            "venue": "bitkub_public",
            "symbol": "BTC_THB",
            "price": 2_000_000.0,
            "ts": now,
            "source": "fixture",
        }
        bnth = {
            "venue": "binance_th",
            "symbol": "BTCTHB",
            "price": 2_001_000.0,
            "ts": now,
            "source": "fixture",
        }
        killed = detect_bitkub_bnth_basis(bitkub, bnth, allow_fixture=False)
        self.assertTrue(killed["kill"])
        self.assertEqual(killed["kill_reason"], "money_leg_source_fixture")
        allowed = detect_bitkub_bnth_basis(bitkub, bnth, allow_fixture=True)
        self.assertFalse(allowed["kill"])
        self.assertTrue(allowed.get("opportunity") or allowed.get("net_basis_bps") is not None)

    def test_stale_kill(self):
        old = (datetime.now(timezone.utc) - timedelta(seconds=120)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        bitkub = {
            "venue": "bitkub_public",
            "symbol": "BTC_THB",
            "price": 2_000_000.0,
            "ts": old,
            "source": "bitkub_v3_market_ticker",
        }
        bnth = {
            "venue": "binance_th",
            "symbol": "BTCTHB",
            "price": 2_001_000.0,
            "ts": old,
            "source": "binance_th_ticker_price",
        }
        out = detect_bitkub_bnth_basis(bitkub, bnth, max_age_sec=30.0)
        self.assertTrue(out["kill"])
        self.assertEqual(out["kill_reason"], "stale")
        self.assertIn("stale", out["soft_flags"])


class PersistFilterTests(unittest.TestCase):
    def test_persist_needs_consecutive(self):
        hist = [
            {"kill": False, "net_basis_bps": 5.0},
            {"kill": False, "net_basis_bps": 6.0},
            {"kill": False, "net_basis_bps": 7.0},
        ]
        ok = opportunity_persisted(hist, min_samples=3, threshold_bps=5.0)
        self.assertTrue(ok["persisted"])
        bad = opportunity_persisted(
            hist[:-1] + [{"kill": False, "net_basis_bps": 1.0}],
            min_samples=3,
            threshold_bps=5.0,
        )
        self.assertFalse(bad["persisted"])


class ScanMockHttpTests(unittest.TestCase):
    def test_scan_mocked_both_venues(self):
        routes = {
            "api.bitkub.com": [
                {
                    "symbol": "BTC_THB",
                    "last": 2_500_000.0,
                    "lowest_ask": 2_500_100.0,
                    "highest_bid": 2_499_900.0,
                }
            ],
            "ticker/price": {"symbol": "BTCTHB", "price": "2505000.00"},
            "ticker/bookTicker": {
                "symbol": "BTCTHB",
                "bidPrice": "2504900.00",
                "askPrice": "2505100.00",
                "bidQty": "0.1",
                "askQty": "0.1",
            },
        }
        with mock.patch(
            "venues.bitkub.paper.urllib.request.urlopen",
            side_effect=_route_urlopen(routes),
        ), mock.patch(
            "venues.binance_th.tape.urllib.request.urlopen",
            side_effect=_route_urlopen(routes),
        ):
            out = scan_bitkub_bnth_basis(
                timeout=1.0,
                allow_fixture=False,
                use_fixture=False,
                fees=BasisFeeConfig(bitkub_taker_bps=5.0, bnth_taker_bps=5.0),
            )
        self.assertIn(out["status"], ("ok", "below_fee_floor"))
        self.assertEqual(out["unit"], "THB")
        self.assertFalse(out["kill"])
        self.assertIn("gross_basis_bps", out)
        self.assertEqual(out["sources"], ["bitkub", "api.binance.th"])

    def test_fetch_failed_soft_flag(self):
        with mock.patch(
            "venues.bitkub.paper.urllib.request.urlopen",
            side_effect=URLError("down"),
        ), mock.patch(
            "venues.binance_th.tape.urllib.request.urlopen",
            side_effect=URLError("down"),
        ):
            out = scan_bitkub_bnth_basis(timeout=1.0, use_fixture=False)
        self.assertTrue(out["kill"])
        self.assertEqual(out["kill_reason"], "fetch_failed")
        self.assertIn("out_of_sync", out["soft_flags"])


class CliTests(unittest.TestCase):
    def test_live_refuse(self):
        rc = pmm_basis_scan.main(["--live"])
        self.assertEqual(rc, 2)

    def test_fixture_allow_cli(self):
        buf = io.StringIO()
        with mock.patch("sys.stdout", buf):
            rc = pmm_basis_scan.main(
                ["--paper", "--fixture", "--allow-fixture", "--prices-only"]
            )
        self.assertEqual(rc, 0)
        data = json.loads(buf.getvalue())
        self.assertIn("gross_basis_bps", data)
        self.assertIn("net_basis_bps", data)


if __name__ == "__main__":
    unittest.main()
