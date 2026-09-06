#!/usr/bin/env python3
"""Solana T2 paper fill → edge_log + scorecard-readable rows."""
from __future__ import annotations

import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
SCRIPTS = ROOT / "scripts"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from venues.solana import jupiter_quotes as jq  # noqa: E402
from venues.solana import paper as sp  # noqa: E402


def _load_script(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    if str(SRC) not in sys.path:
        sys.path.insert(0, str(SRC))
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    spec.loader.exec_module(mod)
    return mod


class SolanaPaperFillTests(unittest.TestCase):
    def test_fill_from_fixture_quote_fee_labeled(self):
        q = jq.fixture_sol_usdc_quote()
        fill = sp.paper_fill_from_quote(q, side="buy")
        self.assertEqual(fill["venue"], "solana_paper")
        self.assertEqual(fill["mode"], "paper")
        self.assertFalse(fill["live"])
        self.assertFalse(fill["signed"])
        self.assertFalse(fill["broadcast"])
        self.assertEqual(fill["side"], "buy")
        self.assertAlmostEqual(fill["px"], 150.0, places=6)
        self.assertIsNotNone(fill["fee_estimate"])
        self.assertEqual(fill["fee_bps_label"], "API_feeBps")
        self.assertIsNotNone(fill["net_out_ui_after_fee_bps"])
        self.assertIsNone(fill["realized_pnl_thb"])
        self.assertIn("never sign", fill["note"].lower())

    def test_fill_fee_unavailable_no_invent(self):
        q = jq.fixture_sol_usdc_quote().to_dict()
        q["fee_bps"] = None
        fill = sp.paper_fill_from_quote(q)
        self.assertIsNone(fill["fee_estimate"])
        self.assertEqual(fill["fee_bps_label"], "unavailable")
        self.assertIsNone(fill["net_out_ui_after_fee_bps"])
        self.assertIsNone(fill["realized_pnl_thb"])

    def test_refuse_live(self):
        with self.assertRaises(sp.SolanaPaperError):
            sp.refuse_live()
        with self.assertRaises(sp.SolanaPaperError):
            sp.live_order_stub()

    def test_simulate_requires_allow_for_fixture(self):
        with self.assertRaises(sp.SolanaPaperError):
            sp.simulate_paper_fill(use_fixture=True, allow_fixture=False)

    def test_batch_five_fills(self):
        out = sp.paper_batch_fills(5, use_fixture=True, allow_fixture=True)
        self.assertTrue(out["ok"])
        self.assertEqual(out["n"], 5)
        self.assertEqual(len(out["fills"]), 5)
        self.assertEqual(out["venue"], "solana_paper")
        self.assertIsNone(out["realized_pnl_thb"])
        venues = {f["venue"] for f in out["fills"]}
        self.assertEqual(venues, {"solana_paper"})


class SolanaPaperEdgeLogScorecardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.edge = _load_script("pmm_edge_log", SCRIPTS / "pmm_edge_log.py")
        cls.score = _load_script("pmm_edge_scorecard", SCRIPTS / "pmm_edge_scorecard.py")
        cls.cli = _load_script("pmm_sol_paper", SCRIPTS / "pmm_sol_paper.py")

    def test_five_paper_rows_edge_log_and_scorecard(self):
        """Proof path: ≥5 solana_paper rows offline → scorecard-readable."""
        batch = sp.paper_batch_fills(5, use_fixture=True, allow_fixture=True)
        with tempfile.TemporaryDirectory() as td:
            log = Path(td) / "edge_log.jsonl"
            written = self.edge.append_edge_log(batch, log_path=log, source="solana_paper")
            self.assertEqual(written["written"], 5)
            lines = [ln for ln in log.read_text(encoding="utf-8").splitlines() if ln.strip()]
            self.assertGreaterEqual(len(lines), 5)
            rows = [json.loads(ln) for ln in lines]
            self.assertTrue(all(r.get("venue") == "solana_paper" for r in rows))
            self.assertTrue(all(r.get("mode") == "paper" for r in rows))
            self.assertTrue(all(r.get("live") is not True for r in rows))
            for r in rows:
                self.assertIn(r.get("side"), ("buy", "sell"))
                self.assertIsNotNone(r.get("px"))
                self.assertIsNotNone(r.get("size"))

            card = self.score.build_scorecard_from_paths(
                log_path=log,
                state_path=Path(td) / "missing_state.json",
                caps_path=Path(td) / "missing_caps.json",
            )
            self.assertEqual(card["n_fills"], 5)
            self.assertFalse(card["live"])
            self.assertIsNone(card["mean_realized_pnl_thb"])
            self.assertIn("logged", card["pnl_basis"].lower())

    def test_cli_live_refuse(self):
        rc = self.cli.main(["--live"])
        self.assertEqual(rc, 2)

    def test_cli_fixture_without_allow(self):
        buf = io.StringIO()
        with mock.patch("sys.stdout", buf):
            rc = self.cli.main(["--fixture"])
        self.assertEqual(rc, 1)
        data = json.loads(buf.getvalue())
        self.assertFalse(data["ok"])

    def test_cli_batch_log_edge_fixture(self):
        with tempfile.TemporaryDirectory() as td:
            log = Path(td) / "edge_log.jsonl"
            buf = io.StringIO()
            with mock.patch("sys.stdout", buf):
                rc = self.cli.main(
                    [
                        "--fixture",
                        "--allow-fixture",
                        "--batch",
                        "5",
                        "--log-edge",
                        "--log",
                        str(log),
                    ]
                )
            self.assertEqual(rc, 0)
            data = json.loads(buf.getvalue())
            self.assertTrue(data["ok"])
            self.assertEqual(data["edge_log"]["written"], 5)
            rows = [json.loads(ln) for ln in log.read_text(encoding="utf-8").splitlines() if ln.strip()]
            self.assertEqual(len(rows), 5)
            self.assertEqual(rows[0]["venue"], "solana_paper")


if __name__ == "__main__":
    unittest.main()
