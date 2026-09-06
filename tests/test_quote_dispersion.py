#!/usr/bin/env python3
"""Tests for Jupiter quote-dispersion logger (fixture offline; --live refuse)."""
from __future__ import annotations

import io
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
SCRIPTS = ROOT / "scripts"
for p in (str(SRC), str(SCRIPTS)):
    if p not in sys.path:
        sys.path.insert(0, p)

from venues.solana import jupiter_quotes as jq  # noqa: E402
from venues.solana import quote_dispersion as qd  # noqa: E402
import pmm_quote_dispersion  # noqa: E402


class SizeDispersionMathTests(unittest.TestCase):
    def test_compute_dispersion(self):
        quotes = [
            {"status": "ok", "mid": 100.0, "in_amount": "1000000"},
            {"status": "ok", "mid": 101.0, "in_amount": "100000000"},
        ]
        out = qd.compute_size_dispersion(quotes)
        self.assertFalse(out["kill"])
        self.assertGreater(out["dispersion_bps"], 0)
        self.assertEqual(out["n_ok"], 2)

    def test_empty_fail_closed(self):
        out = qd.compute_size_dispersion(
            [{"status": "empty", "mid": None, "in_amount": "1"}]
        )
        self.assertTrue(out["kill"])
        self.assertIsNone(out["dispersion_bps"])


class FixtureKillTests(unittest.TestCase):
    def test_size_quote_fixture_requires_allow(self):
        with self.assertRaises(qd.DispersionError):
            qd.fetch_jupiter_size_quote("100000000", use_fixture=True, allow_fixture=False)

    def test_size_quote_fixture_ok(self):
        q = qd.fetch_jupiter_size_quote(
            "100000000", use_fixture=True, allow_fixture=True
        )
        self.assertEqual(q["status"], "ok")
        self.assertTrue(q["fixture"])
        self.assertGreater(q["mid"], 0)

    def test_scan_fixture_kill_without_allow(self):
        # Inject fixture-looking quotes via quote_fn path is hard; use use_fixture
        # without allow -> DispersionError on first size, but scan catches via
        # fetch raising... fetch raises DispersionError. Wrap: use fixture + no allow
        # should raise before scan completes — scan calls fetch which raises.
        with self.assertRaises(qd.DispersionError):
            qd.scan_quote_dispersion(
                use_fixture=True,
                allow_fixture=False,
                probe_pools=False,
                snaps=1,
                sizes=["1000000", "10000000"],
            )

    def test_scan_fixture_allowed(self):
        out = qd.scan_quote_dispersion(
            use_fixture=True,
            allow_fixture=True,
            probe_pools=False,
            snaps=1,
            sizes=["1000000", "10000000", "100000000"],
        )
        self.assertFalse(out["kill"])
        self.assertGreaterEqual(out["snaps_ok"], 1)
        latest = out["latest"]
        self.assertIn("fee_slip_stack", latest)
        self.assertIn("size_dispersion", latest)
        self.assertIsNotNone(latest["size_dispersion"].get("dispersion_bps"))


class FailClosedTests(unittest.TestCase):
    def test_rate_limit_no_invented_mid(self):
        def boom(**kwargs):
            raise jq.JupiterQuoteError("HTTP 429 rate_limit")

        out = qd.scan_quote_dispersion(
            quote_fn=boom,
            probe_pools=False,
            snaps=1,
            sizes=["1000000", "10000000"],
        )
        self.assertTrue(out["kill"])
        self.assertEqual(out["kill_reason"], "rate_limit")
        for snap in out["samples"]:
            for q in snap["quotes"]:
                self.assertIsNone(q.get("mid"))
                self.assertEqual(q.get("status"), "rate_limit")

    def test_empty_error_no_invented_mid(self):
        def boom(**kwargs):
            raise jq.JupiterQuoteError("HTTP 500 empty")

        out = qd.scan_quote_dispersion(
            quote_fn=boom,
            probe_pools=False,
            snaps=1,
            sizes=["1000000"],
        )
        self.assertTrue(out["kill"])
        self.assertIn(out["kill_reason"], ("empty", "no_valid_mids", "empty_or_error"))
        self.assertIsNone(out["latest"]["quotes"][0].get("mid"))


class ThesisTwentySnapsTests(unittest.TestCase):
    def test_twenty_snaps_fixture_offline(self):
        out = qd.scan_quote_dispersion(
            use_fixture=True,
            allow_fixture=True,
            probe_pools=False,
            snaps=20,
            sizes=["1000000", "10000000", "100000000"],
        )
        self.assertEqual(out["snaps"], 20)
        self.assertEqual(out["snaps_ok"], 20)
        self.assertFalse(out["kill"])
        self.assertEqual(len(out["samples"]), 20)
        # Ledger-shaped artifact
        self.assertEqual(out["lane"], "jupiter_quote_dispersion")
        self.assertFalse(out["live"])
        self.assertEqual(out["execution"], "scan_only")
        for s in out["samples"]:
            self.assertIn("fee_slip_stack", s)
            self.assertIn("fee_bps", s["fee_slip_stack"])
            self.assertIn("slippage_bps", s["fee_slip_stack"])


class PoolDeferredTests(unittest.TestCase):
    def test_pool_fixture_kill(self):
        r = qd.fetch_pool_mid_raydium(use_fixture=True, allow_fixture=False)
        self.assertEqual(r["status"], "kill")
        self.assertIsNone(r["mid"])

    def test_compare_skips_deferred(self):
        pools = {
            "raydium": {"status": "deferred", "mid": None},
            "orca": {"status": "ok", "mid": 149.0},
            "meteora": {"status": "deferred", "mid": None},
        }
        cmp = qd.compare_jupiter_vs_pools(150.0, pools)
        self.assertEqual(cmp["comparisons"]["raydium"]["status"], "deferred")
        self.assertEqual(cmp["comparisons"]["orca"]["status"], "ok")
        self.assertIsNotNone(cmp["comparisons"]["orca"]["dispersion_bps"])


class CliTests(unittest.TestCase):
    def test_live_refuse(self):
        buf = io.StringIO()
        with mock.patch("sys.stdout", buf):
            rc = pmm_quote_dispersion.main(["--live"])
        self.assertEqual(rc, 2)
        data = json.loads(buf.getvalue())
        self.assertFalse(data["ok"])
        self.assertIn("REFUSED", data["error"])

    def test_fixture_cli_twenty(self):
        buf = io.StringIO()
        with mock.patch("sys.stdout", buf):
            rc = pmm_quote_dispersion.main(
                [
                    "--fixture",
                    "--allow-fixture",
                    "--no-pools",
                    "--snaps",
                    "20",
                    "--prices-only",
                ]
            )
        self.assertEqual(rc, 0)
        data = json.loads(buf.getvalue())
        self.assertTrue(data["ok"])
        self.assertEqual(data["snaps"], 20)
        self.assertFalse(data["live"])
        self.assertIsNotNone(data.get("dispersion_bps"))

    def test_ledger_artifact(self):
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            ledger = Path(td) / "quote_dispersion_ledger.jsonl"
            buf = io.StringIO()
            with mock.patch("sys.stdout", buf):
                rc = pmm_quote_dispersion.main(
                    [
                        "--fixture",
                        "--allow-fixture",
                        "--no-pools",
                        "--snaps",
                        "3",
                        "--log",
                        "--ledger",
                        str(ledger),
                    ]
                )
            self.assertEqual(rc, 0)
            self.assertTrue(ledger.exists())
            lines = ledger.read_text(encoding="utf-8").strip().splitlines()
            self.assertEqual(len(lines), 1)
            row = json.loads(lines[0])
            self.assertEqual(row["snaps"], 3)
            self.assertEqual(row["lane"], "jupiter_quote_dispersion")


class FeeSlipTests(unittest.TestCase):
    def test_api_labels(self):
        stack = qd.fee_slip_from_quote(
            {"fee_bps": 2.0, "slippage_bps": 50, "prioritization_fee_lamports": 1000}
        )
        d = stack.to_dict()
        self.assertEqual(d["fee_bps_label"], "API_feeBps")
        self.assertEqual(d["slippage_bps_label"], "API_slippageBps")

    def test_estimate_labels(self):
        stack = qd.fee_slip_from_quote({})
        d = stack.to_dict()
        self.assertEqual(d["fee_bps_label"], "ESTIMATE")
        self.assertEqual(d["slippage_bps_label"], "ESTIMATE")


if __name__ == "__main__":
    unittest.main()
