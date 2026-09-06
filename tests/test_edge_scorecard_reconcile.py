#!/usr/bin/env python3
"""Unit tests for edge scorecard, triple-tape divergence, paper reconcile."""
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
SCRIPTS = ROOT / "scripts"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from venues.divergence import (  # noqa: E402
    compute_triple_tape_divergence,
    pair_divergence,
    quote_currency,
)


def _load_script(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


class DivergenceTests(unittest.TestCase):
    def test_quote_currency(self):
        self.assertEqual(quote_currency("BTCUSDT"), "USDT")
        self.assertEqual(quote_currency("WBTC-USD"), "USD")
        self.assertEqual(quote_currency("BTC_THB"), "THB")

    def test_same_currency_numeric(self):
        a = {"venue": "binance_public", "symbol": "BTCUSDT", "price": 100.0, "ts": "t", "source": "s"}
        b = {"venue": "oneinch", "symbol": "WBTC-USD", "price": 98.0, "ts": "t", "source": "s"}
        d = pair_divergence(a, b)
        self.assertTrue(d["comparable"])
        self.assertEqual(d["status"], "ok")
        self.assertAlmostEqual(d["abs_diff"], 2.0)
        self.assertAlmostEqual(d["px_ratio_a_over_b"], 100.0 / 98.0)

    def test_cross_currency_unit_mismatch_no_fx(self):
        a = {"venue": "binance_public", "symbol": "BTCUSDT", "price": 65000.0, "ts": "t", "source": "s"}
        b = {"venue": "bitkub_public", "symbol": "BTC_THB", "price": 2300000.0, "ts": "t", "source": "s"}
        d = pair_divergence(a, b)
        self.assertFalse(d["comparable"])
        self.assertEqual(d["status"], "unit_mismatch")
        self.assertIsNone(d["abs_diff"])
        self.assertIsNone(d["px_ratio_a_over_b"])

    def test_cross_currency_with_labeled_fx(self):
        a = {"venue": "binance_public", "symbol": "BTCUSDT", "price": 65000.0, "ts": "t", "source": "s"}
        b = {"venue": "bitkub_public", "symbol": "BTC_THB", "price": 2275000.0, "ts": "t", "source": "s"}
        fx = {"price": 35.0, "source": "binance_ticker_price_USDTTHB", "ts": "t"}
        d = pair_divergence(a, b, usdthb=fx)
        self.assertTrue(d["comparable"])
        self.assertEqual(d["status"], "fx_adjusted")
        self.assertEqual(d["fx"]["source"], "binance_ticker_price_USDTTHB")
        # 2275000/35 = 65000 → abs_diff ~ 0
        self.assertAlmostEqual(d["abs_diff"], 0.0, places=4)

    def test_triple_tape_summary(self):
        tape = [
            {"venue": "binance_public", "symbol": "BTCUSDT", "price": 100.0, "ts": "t1", "source": "a"},
            {"venue": "oneinch", "symbol": "WBTC-USD", "price": 101.0, "ts": "t2", "source": "b"},
            {"venue": "bitkub_public", "symbol": "BTC_THB", "price": 3500.0, "ts": "t3", "source": "c"},
        ]
        out = compute_triple_tape_divergence(tape)
        self.assertEqual(out["n_mids"], 3)
        self.assertEqual(out["n_comparable_pairs"], 1)  # USD-like only
        self.assertEqual(out["n_unit_mismatch_pairs"], 2)


class EdgeScorecardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = _load_script("pmm_edge_scorecard", SCRIPTS / "pmm_edge_scorecard.py")

    def test_fixture_jsonl_mean_pnl(self):
        fixture = [
            {
                "leg": "open",
                "round_trip_id": "rt1",
                "side": "buy",
                "px": 100,
                "size": 1,
                "realized_pnl_thb": None,
                "mode": "paper",
            },
            {
                "leg": "close",
                "round_trip_id": "rt1",
                "side": "sell",
                "px": 99,
                "size": 1,
                "realized_pnl_thb": -1.5,
                "mode": "paper",
            },
            {
                "leg": "open",
                "round_trip_id": "rt2",
                "side": "buy",
                "px": 100,
                "size": 1,
                "realized_pnl_thb": None,
                "mode": "paper",
            },
            {
                "leg": "close",
                "round_trip_id": "rt2",
                "side": "sell",
                "px": 102,
                "size": 1,
                "realized_pnl_thb": 2.0,
                "mode": "paper",
            },
        ]
        with tempfile.TemporaryDirectory() as td:
            log = Path(td) / "edge_log.jsonl"
            log.write_text("\n".join(json.dumps(r) for r in fixture) + "\n", encoding="utf-8")
            state = Path(td) / "bitkub_paper_day_state.json"
            state.write_text(
                json.dumps(
                    {
                        "day": "2026-09-06",
                        "trades": 2,
                        "realized_pnl_thb": 0.5,
                        "stopped": True,
                        "stop_reason": "max_trades_per_day=2",
                    }
                ),
                encoding="utf-8",
            )
            out = self.mod.build_scorecard_from_paths(
                log_path=log,
                state_path=state,
                caps_path=Path(td) / "missing_caps.json",
            )
        self.assertEqual(out["n_fills"], 4)
        self.assertEqual(out["n_round_trips"], 2)
        self.assertAlmostEqual(out["mean_realized_pnl_thb"], 0.25)
        self.assertEqual(out["hit_count"], 1)
        self.assertEqual(out["miss_count"], 1)
        self.assertIsNone(out["fill_rate"])  # no skip data
        self.assertIn("no skip data", out["fill_rate_note"].lower())
        self.assertTrue(out["day_cap_stop"]["present"])
        self.assertTrue(out["day_cap_stop"]["stopped"])
        self.assertEqual(out["day_cap_stop"]["stop_reason"], "max_trades_per_day=2")
        # Refuse inventing: mean uses logged fields only
        self.assertIn("logged", out["pnl_basis"].lower())

    def test_fill_rate_with_skips(self):
        records = [
            {"side": "buy", "px": 1, "realized_pnl_thb": None, "mode": "paper"},
            {"side": "sell", "px": 1, "realized_pnl_thb": -0.1, "mode": "paper"},
        ]
        skips = [{"event": "skip", "reason": "cap"}, {"event": "skip", "reason": "noise"}]
        out = self.mod.compute_scorecard(records, skip_events=skips)
        self.assertEqual(out["n_fills"], 2)
        self.assertAlmostEqual(out["fill_rate"], 0.5)
        self.assertEqual(out["n_skips"], 2)

    def test_empty_log_no_invented_pnl(self):
        out = self.mod.compute_scorecard([])
        self.assertEqual(out["n_fills"], 0)
        self.assertIsNone(out["mean_realized_pnl_thb"])
        self.assertFalse(out["live"])

    def test_refuse_live_record(self):
        with tempfile.TemporaryDirectory() as td:
            log = Path(td) / "edge_log.jsonl"
            log.write_text(json.dumps({"live": True, "side": "buy", "px": 1}) + "\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                self.mod.load_edge_records(log)


class PaperReconcileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = _load_script("pmm_paper_reconcile", SCRIPTS / "pmm_paper_reconcile.py")

    def test_write_sets_session_closed(self):
        with tempfile.TemporaryDirectory() as td:
            rt = Path(td)
            log = rt / "edge_log.jsonl"
            log.write_text(
                json.dumps(
                    {
                        "leg": "close",
                        "realized_pnl_thb": -0.2,
                        "mode": "paper",
                        "round_trip_id": "x",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            (rt / "bitkub_paper_day_state.json").write_text(
                json.dumps({"day": "2026-09-06", "trades": 1, "stopped": False, "realized_pnl_thb": -0.2}),
                encoding="utf-8",
            )
            out = self.mod.write_reconcile(runtime_dir=rt, session_closed=True, ts="20260906T000000Z")
            path = Path(out["reconcile_path"])
            self.assertTrue(path.exists())
            self.assertTrue(out["session_closed"])
            disk = json.loads(path.read_text(encoding="utf-8"))
            self.assertTrue(disk["session_closed"])
            self.assertTrue(disk["checklist"]["open_paper_positions"]["flat"])
            self.assertIn("manual_steps_future_live", disk["checklist"])
            self.assertGreaterEqual(len(disk["checklist"]["manual_steps_future_live"]), 3)
            self.assertEqual(len(disk["checklist"]["edge_log_tails"]["records"]), 1)

    def test_preview_blocks_session_closed(self):
        with tempfile.TemporaryDirectory() as td:
            rt = Path(td)
            payload = self.mod.build_reconcile_payload(
                runtime_dir=rt,
                log_path=rt / "edge_log.jsonl",
                state_path=rt / "bitkub_paper_day_state.json",
                caps_path=rt / "bitkub_paper_day_caps.json",
                mark_session_closed=False,
            )
        self.assertFalse(payload["session_closed"])

    def test_claim_without_artifact_blocked(self):
        blocked = self.mod.claim_session_closed_without_artifact()
        self.assertFalse(blocked["session_closed"])
        self.assertFalse(blocked["ok"])


class DoctorNewScriptsPresenceTests(unittest.TestCase):
    def test_new_scripts_exist(self):
        for rel in (
            "scripts/pmm_edge_scorecard.py",
            "scripts/pmm_paper_reconcile.py",
            "src/venues/divergence.py",
        ):
            self.assertTrue((ROOT / rel).exists(), msg=rel)


if __name__ == "__main__":
    unittest.main()
