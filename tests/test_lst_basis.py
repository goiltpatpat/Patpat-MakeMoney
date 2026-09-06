#!/usr/bin/env python3
"""Unit tests for LST basis (Marinade/jitoSOL fair vs Jupiter; mocked HTTP/RPC)."""
from __future__ import annotations

import struct
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
SCRIPTS = ROOT / "scripts"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from venues.basis.lst import (  # noqa: E402
    LstFeeConfig,
    compute_lst_basis_bps,
    decode_stake_pool_ratio,
    detect_lst_basis,
    fetch_jitosol_fair_rate,
    fetch_jupiter_lst_sol_leg,
    fetch_msol_fair_rate,
    scan_lst_basis,
)
import pmm_lst_basis_scan  # noqa: E402


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _fake_stake_pool_bytes(total_lamports: int, pool_token_supply: int) -> bytes:
    data = bytearray(280)
    struct.pack_into("<Q", data, 258, int(total_lamports))
    struct.pack_into("<Q", data, 266, int(pool_token_supply))
    return bytes(data)


class DecodeStakePoolTests(unittest.TestCase):
    def test_ratio(self):
        # 1.25 SOL per LST
        data = _fake_stake_pool_bytes(1_250_000_000, 1_000_000_000)
        out = decode_stake_pool_ratio(data)
        self.assertEqual(out["total_lamports"], 1_250_000_000)
        self.assertEqual(out["pool_token_supply"], 1_000_000_000)
        self.assertAlmostEqual(out["sol_per_lst"], 1.25)

    def test_short_account(self):
        with self.assertRaises(Exception):
            decode_stake_pool_ratio(b"\x00" * 10)


class FairRateTests(unittest.TestCase):
    def test_msol_fixture_requires_allow(self):
        with self.assertRaises(Exception):
            fetch_msol_fair_rate(use_fixture=True, allow_fixture=False)
        ok = fetch_msol_fair_rate(use_fixture=True, allow_fixture=True)
        self.assertTrue(ok["fixture"])
        self.assertAlmostEqual(ok["sol_per_lst"], 1.40)

    def test_jitosol_from_account_data(self):
        data = _fake_stake_pool_bytes(1_200_000_000, 1_000_000_000)
        out = fetch_jitosol_fair_rate(account_data=data)
        self.assertAlmostEqual(out["sol_per_lst"], 1.2)
        self.assertEqual(out["source"], "jito_spl_stake_pool_rpc")
        self.assertFalse(out["fixture"])


class BasisMathTests(unittest.TestCase):
    def test_compute_premium(self):
        # jupiter 1.402 vs fair 1.40 → small premium
        out = compute_lst_basis_bps(1.40, 1.402)
        self.assertGreater(out["gross_basis_bps"], 0)
        self.assertIn("Jupiter richer", out["sign_convention"])

    def test_detect_net_estimate(self):
        now = _now()
        fair = {
            "lst": "mSOL",
            "mint": "mSoLzYCxHdYgdzU16g5QSh3i5K3z3KZK7ytfqcJm7So",
            "sol_per_lst": 1.40,
            "ts": now,
            "source": "marinade_msol_price_sol",
        }
        jup = {
            "lst": "mSOL",
            "venue": "jupiter_solana",
            "symbol": "mSOL/SOL",
            "sol_per_lst": 1.414,  # ~100 bps premium
            "ts": now,
            "source": "jupiter_swap_v2_order",
            "fee_bps_api": 2.0,
            "route_labels": ["Raydium", "Orca"],
        }
        fees = LstFeeConfig(jupiter_fee_bps=5.0)
        out = detect_lst_basis(fair, jup, fees=fees)
        self.assertFalse(out["kill"])
        self.assertEqual(out["lane"], "lst_fair_vs_jupiter")
        self.assertEqual(out["direction"], "jupiter_rich")
        self.assertEqual(out["net_basis_bps_label"], "ESTIMATE")
        self.assertEqual(out["fee_floor_source"], "API_feeBps")
        self.assertAlmostEqual(out["fee_floor_bps"], 2.0)
        self.assertIn("Raydium", out["dispersion_hint"]["route_labels"])

    def test_fixture_kill_unless_allowed(self):
        now = _now()
        fair = {
            "lst": "mSOL",
            "sol_per_lst": 1.40,
            "ts": now,
            "source": "fixture",
            "fixture": True,
        }
        jup = {
            "lst": "mSOL",
            "sol_per_lst": 1.41,
            "ts": now,
            "source": "fixture",
            "fixture": True,
        }
        killed = detect_lst_basis(fair, jup, allow_fixture=False)
        self.assertTrue(killed["kill"])
        self.assertEqual(killed["kill_reason"], "money_leg_source_fixture")
        allowed = detect_lst_basis(fair, jup, allow_fixture=True)
        self.assertFalse(allowed["kill"])

    def test_stale_kill(self):
        old = (datetime.now(timezone.utc) - timedelta(seconds=120)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        fair = {
            "lst": "jitoSOL",
            "sol_per_lst": 1.2,
            "ts": old,
            "source": "jito_spl_stake_pool_rpc",
        }
        jup = {
            "lst": "jitoSOL",
            "sol_per_lst": 1.19,
            "ts": old,
            "source": "jupiter_swap_v2_order",
        }
        out = detect_lst_basis(fair, jup, max_age_sec=30.0)
        self.assertTrue(out["kill"])
        self.assertEqual(out["kill_reason"], "stale")

    def test_unit_mismatch(self):
        now = _now()
        fair = {"lst": "mSOL", "sol_per_lst": 1.4, "ts": now, "source": "x"}
        jup = {"lst": "jitoSOL", "sol_per_lst": 1.2, "ts": now, "source": "y"}
        out = detect_lst_basis(fair, jup)
        self.assertTrue(out["kill"])
        self.assertEqual(out["kill_reason"], "unit_mismatch")


class ScanFixtureTests(unittest.TestCase):
    def test_scan_fixture_kill(self):
        out = scan_lst_basis(use_fixture=True, allow_fixture=False)
        self.assertTrue(out["kill"])
        self.assertTrue((out.get("msol") or {}).get("kill"))

    def test_scan_fixture_allowed(self):
        out = scan_lst_basis(use_fixture=True, allow_fixture=True)
        self.assertFalse(out["kill"])
        msol = out["msol"]
        self.assertFalse(msol["kill"])
        self.assertEqual(msol["net_basis_bps_label"], "ESTIMATE")
        self.assertIn("gross_basis_bps", msol)
        jito = out["jitosol"]
        self.assertFalse(jito["kill"])


class CliTests(unittest.TestCase):
    def test_live_refuse(self):
        rc = pmm_lst_basis_scan.main(["--live"])
        self.assertEqual(rc, 2)

    def test_fixture_prices_only(self):
        buf = mock.mock_open()
        with mock.patch("builtins.print") as pr:
            rc = pmm_lst_basis_scan.main(
                ["--paper", "--fixture", "--allow-fixture", "--prices-only"]
            )
        self.assertEqual(rc, 0)
        # last print should include msol_fair
        printed = " ".join(str(c.args[0]) for c in pr.call_args_list)
        self.assertIn("msol_fair", printed)
        self.assertIn("ESTIMATE", printed)


if __name__ == "__main__":
    unittest.main()
