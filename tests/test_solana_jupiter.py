"""Tests for Solana Jupiter research quote lane (mocked; no live swaps)."""
from __future__ import annotations

import io
import json
import sys
import unittest
from pathlib import Path
from unittest import mock
from urllib.error import HTTPError

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
SCRIPTS = ROOT / "scripts"
for p in (str(SRC), str(SCRIPTS)):
    if p not in sys.path:
        sys.path.insert(0, p)

from venues.solana import jupiter_quotes as jq  # noqa: E402
from venues.arb import sol_cex  # noqa: E402
import pmm_sol_tape  # noqa: E402


SAMPLE_ORDER = {
    "inputMint": jq.SOL_MINT,
    "inAmount": "100000000",
    "outputMint": jq.USDC_MINT,
    "outAmount": "15000000",
    "priceImpactPct": "0.01",
    "slippageBps": 50,
    "feeBps": 2,
    "prioritizationFeeLamports": 5000,
    "router": "metis",
    "mode": "ultra",
    "requestId": "test-req",
    "transaction": None,
    "routePlan": [
        {"swapInfo": {"label": "MockDex"}, "percent": 100},
    ],
}


class JupiterQuotesTests(unittest.TestCase):
    def test_fixture_requires_allow(self):
        with self.assertRaises(jq.JupiterQuoteError):
            jq.fetch_jupiter_order_quote(use_fixture=True, allow_fixture=False)

    def test_fixture_ok_with_allow(self):
        q = jq.fetch_jupiter_order_quote(use_fixture=True, allow_fixture=True)
        self.assertEqual(q.source, "fixture")
        self.assertGreater(q.mid, 0)
        self.assertEqual(q.out_amount, str(int(round(0.1 * 150.0 * 1_000_000))))

    def test_parse_order_mid_and_route(self):
        q = jq._parse_order_payload(
            SAMPLE_ORDER,
            input_mint=jq.SOL_MINT,
            output_mint=jq.USDC_MINT,
            input_decimals=9,
            output_decimals=6,
            source="jupiter_swap_v2_order",
        )
        self.assertAlmostEqual(q.mid, 150.0, places=6)
        self.assertEqual(q.out_amount, "15000000")
        self.assertEqual(q.route_labels, ["MockDex"])
        self.assertEqual(q.prioritization_fee_lamports, 5000)
        self.assertIn("estimate", (q.prioritization_fee_label or "").lower())
        d = q.to_dict()
        self.assertFalse(d["live"])
        self.assertEqual(d["execution"], "quote_only")

    def test_fetch_order_mocked(self):
        with mock.patch.object(jq, "_get_json", return_value=SAMPLE_ORDER):
            q = jq.fetch_jupiter_order_quote(allow_fixture=False, use_fixture=False)
        self.assertEqual(q.source, "jupiter_swap_v2_order")
        self.assertAlmostEqual(q.mid, 150.0, places=6)
        self.assertEqual(q.price_impact_pct, 0.01)

    def test_fetch_order_http_fail_closed(self):
        err = HTTPError("https://api.jup.ag/x", 500, "err", hdrs=None, fp=io.BytesIO(b"nope"))
        with mock.patch.object(jq, "_get_json", side_effect=jq.JupiterQuoteError("HTTP 500")):
            with self.assertRaises(jq.JupiterQuoteError):
                jq.fetch_jupiter_order_quote(allow_fixture=False)

    def test_price_v3_mocked(self):
        payload = {
            jq.SOL_MINT: {
                "usdPrice": 149.5,
                "decimals": 9,
                "blockId": 1,
            }
        }
        with mock.patch.object(jq, "_get_json", return_value=payload):
            t = jq.fetch_jupiter_usd_price(jq.SOL_MINT)
        self.assertEqual(t.source, "jupiter_price_v3")
        self.assertAlmostEqual(t.price, 149.5)

    def test_no_taker_in_url(self):
        captured = {}

        def fake_get(url, *, api_key, timeout):
            captured["url"] = url
            return SAMPLE_ORDER

        with mock.patch.object(jq, "_get_json", side_effect=fake_get):
            jq.fetch_jupiter_order_quote()
        self.assertIn("/swap/v2/order", captured["url"])
        self.assertNotIn("taker=", captured["url"])
        self.assertIn("inputMint=", captured["url"])


class SolCexStubTests(unittest.TestCase):
    def test_fixture_kill(self):
        sol = jq.fixture_sol_usdc_quote().to_dict()
        bnth = {
            "venue": "binance_th",
            "symbol": "SOLUSDT",
            "price": 151.0,
            "ts": "t",
            "source": "fixture",
        }
        out = sol_cex.detect_sol_vs_bnth(
            sol, bnth, usdt_usdc_one_to_one=True, allow_fixture=False
        )
        self.assertTrue(out["kill"])
        self.assertEqual(out["kill_reason"], "money_leg_source_fixture")

    def test_same_stable_scores(self):
        sol = {
            "venue": "jupiter_solana",
            "symbol": "SOL/USDC",
            "mid": 100.0,
            "ts": "t",
            "source": "jupiter_swap_v2_order",
            "out_amount": "1",
        }
        bnth = {
            "venue": "binance_th",
            "symbol": "SOLUSDT",
            "price": 101.0,
            "ts": "t",
            "source": "binance_th_ticker_price",
        }
        out = sol_cex.detect_sol_vs_bnth(
            sol, bnth, usdt_usdc_one_to_one=True, allow_fixture=False
        )
        self.assertNotEqual(out.get("kill_reason"), "unit_mismatch")
        self.assertTrue(out.get("comparable") or out.get("gross_spread_bps") is not None)
        self.assertIsNotNone(out.get("same_stable_path"))

    def test_unit_mismatch_without_path(self):
        sol = {
            "venue": "jupiter_solana",
            "symbol": "SOL/USDC",
            "mid": 100.0,
            "ts": "t",
            "source": "live_mock",
        }
        bnth = {
            "venue": "binance_th",
            "symbol": "SOLTHB",
            "price": 3600.0,
            "ts": "t",
            "source": "live_mock",
        }
        out = sol_cex.detect_sol_vs_bnth(sol, bnth, allow_fixture=False)
        self.assertTrue(out["kill"])
        self.assertEqual(out["kill_reason"], "unit_mismatch")


class SolTapeCliTests(unittest.TestCase):
    def test_live_refuse(self):
        rc = pmm_sol_tape.main(["--live"])
        self.assertEqual(rc, 2)

    def test_fixture_without_allow(self):
        buf = io.StringIO()
        with mock.patch("sys.stdout", buf):
            rc = pmm_sol_tape.main(["--fixture"])
        self.assertEqual(rc, 1)
        data = json.loads(buf.getvalue())
        self.assertFalse(data["ok"])

    def test_fixture_cli(self):
        buf = io.StringIO()
        with mock.patch("sys.stdout", buf):
            rc = pmm_sol_tape.main(["--fixture", "--allow-fixture"])
        self.assertEqual(rc, 0)
        data = json.loads(buf.getvalue())
        self.assertTrue(data["ok"])
        self.assertEqual(data["quote"]["source"], "fixture")
        self.assertIn("gross_vs_net", data)
        self.assertIn("mid", data)
        self.assertIn("out_amount", data)


if __name__ == "__main__":
    unittest.main()
