"""Tests for Solana Jupiter research quote lane (mocked; no live swaps)."""
from __future__ import annotations

import io
import json
import os
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

from venues.solana import desk_balance as db  # noqa: E402
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

SAMPLE_ORDER_NO_PRIO = {
    **{k: v for k, v in SAMPLE_ORDER.items() if k != "prioritizationFeeLamports"},
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
        # Fee / priority / slippage stay present + labeled on sol tape JSON
        self.assertEqual(d["fee_bps"], 2.0)
        self.assertEqual(d["slippage_bps"], 50)
        self.assertEqual(d["prioritization_fee_lamports"], 5000)

    def test_parse_order_missing_priority_labeled(self):
        q = jq._parse_order_payload(
            SAMPLE_ORDER_NO_PRIO,
            input_mint=jq.SOL_MINT,
            output_mint=jq.USDC_MINT,
            input_decimals=9,
            output_decimals=6,
            source="jupiter_swap_v2_order",
        )
        self.assertIsNone(q.prioritization_fee_lamports)
        self.assertIn("unavailable", (q.prioritization_fee_label or "").lower())

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


class DeskBalanceTests(unittest.TestCase):
    def test_resolve_pubkey_explicit(self):
        pk = db.resolve_desk_pubkey("7W3SPbRcGD1GJPpafEYhgduaMxLpmHBG9KGqytqZEhHf")
        self.assertTrue(pk.startswith("7W3"))

    def test_resolve_pubkey_from_env(self):
        with mock.patch.dict(os.environ, {"PMM_SOL_DESK_PUBKEY": "EnvPubKey111"}, clear=False):
            self.assertEqual(db.resolve_desk_pubkey(None), "EnvPubKey111")
            self.assertEqual(db.resolve_desk_pubkey(""), "EnvPubKey111")

    def test_resolve_pubkey_missing(self):
        env = {k: v for k, v in os.environ.items() if k != "PMM_SOL_DESK_PUBKEY"}
        with mock.patch.dict(os.environ, env, clear=True):
            with self.assertRaises(db.DeskBalanceError):
                db.resolve_desk_pubkey(None)

    def test_fetch_balance_mocked(self):
        calls = []

        def fake_rpc(rpc_url, method, params, *, timeout=15.0):
            calls.append(method)
            if method == "getBalance":
                return {"context": {"slot": 1}, "value": 2_500_000}
            if method == "getTokenAccountsByOwner":
                prog = params[1]["programId"]
                if prog == db.TOKEN_PROGRAM_ID:
                    return {
                        "value": [
                            {
                                "account": {
                                    "data": {
                                        "parsed": {
                                            "info": {
                                                "mint": jq.USDC_MINT,
                                                "tokenAmount": {
                                                    "amount": "1000000",
                                                    "decimals": 6,
                                                    "uiAmount": 1.0,
                                                },
                                            }
                                        }
                                    }
                                }
                            }
                        ]
                    }
                return {"value": []}
            raise AssertionError(method)

        with mock.patch.object(db, "_rpc_call", side_effect=fake_rpc):
            bal = db.fetch_desk_balance(
                "7W3SPbRcGD1GJPpafEYhgduaMxLpmHBG9KGqytqZEhHf",
                include_token_accounts=True,
            )
        self.assertTrue(bal.ok)
        self.assertEqual(bal.lamports, 2_500_000)
        self.assertAlmostEqual(bal.sol, 0.0025)
        self.assertEqual(bal.token_account_count, 1)
        self.assertEqual(bal.tokens[0].mint, jq.USDC_MINT)
        self.assertFalse(bal.live)
        self.assertEqual(bal.execution, "balance_readonly")
        self.assertIn("getBalance", calls)

    def test_never_opens_secret_paths(self):
        """Balance probe must not touch PMM_SOL_SECRETS_DIR / seed files."""
        with mock.patch.dict(
            os.environ,
            {
                "PMM_SOL_DESK_PUBKEY": "7W3SPbRcGD1GJPpafEYhgduaMxLpmHBG9KGqytqZEhHf",
                "PMM_SOL_SECRETS_DIR": "C:\\should\\never\\open",
            },
            clear=False,
        ):
            with mock.patch("builtins.open", side_effect=AssertionError("opened file")):
                with mock.patch.object(
                    db,
                    "_rpc_call",
                    return_value={"context": {"slot": 1}, "value": 0},
                ):
                    bal = db.fetch_desk_balance(include_token_accounts=False)
        self.assertTrue(bal.ok)
        self.assertEqual(bal.lamports, 0)


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
        gvn = data["gross_vs_net"]
        self.assertIn("fee_bps", gvn)
        self.assertIn("fee_bps_label", gvn)
        self.assertIn("slippage_bps", gvn)
        self.assertIn("slippage_bps_label", gvn)
        self.assertIn("prioritization_fee_lamports", gvn)
        self.assertIn("prioritization_fee_label", gvn)
        self.assertIn("mid", data)
        self.assertIn("out_amount", data)
        self.assertIn("smoke_sol_note", data)

    def test_balance_only_cli_mocked(self):
        fake = db.DeskBalanceProbe(
            ok=True,
            pubkey="7W3SPbRcGD1GJPpafEYhgduaMxLpmHBG9KGqytqZEhHf",
            rpc_url="https://api.mainnet-beta.solana.com",
            lamports=1_000_000,
            sol=0.001,
            token_account_count=0,
            tokens=[],
            ts="t",
        )
        buf = io.StringIO()
        with mock.patch.object(pmm_sol_tape, "fetch_desk_balance", return_value=fake):
            with mock.patch("sys.stdout", buf):
                rc = pmm_sol_tape.main(
                    [
                        "--balance-only",
                        "--balance-pubkey",
                        "7W3SPbRcGD1GJPpafEYhgduaMxLpmHBG9KGqytqZEhHf",
                    ]
                )
        self.assertEqual(rc, 0)
        data = json.loads(buf.getvalue())
        self.assertTrue(data["ok"])
        self.assertEqual(data["balance"]["lamports"], 1_000_000)
        self.assertNotIn("quote", data)


if __name__ == "__main__":
    unittest.main()
