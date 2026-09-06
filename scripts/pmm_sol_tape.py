#!/usr/bin/env python3
"""Solana Jupiter research tape CLI — Ledger JSON (quote-only; --live refused).

Never signs or sends. Uses GET /swap/v2/order WITHOUT taker + optional Price V3.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from venues.solana.jupiter_quotes import (  # noqa: E402
    SOL_MINT,
    USDC_MINT,
    JupiterQuoteError,
    fetch_jupiter_order_quote,
    fetch_jupiter_usd_price,
)


def _refuse_live() -> dict[str, Any]:
    return {
        "ok": False,
        "live": False,
        "error": (
            "REFUSED: --live is not implemented for Solana. "
            "Research/dry-run quote tape only — never sign/send; no custody."
        ),
        "mode": "research_dry_run",
        "execution": "quote_only",
    }


def _gross_vs_net(quote: dict[str, Any]) -> dict[str, Any]:
    """Label fee/slippage/priority-fee estimates vs gross mid (no invented costs)."""
    fee_bps = quote.get("fee_bps")
    slip = quote.get("slippage_bps")
    prio = quote.get("prioritization_fee_lamports")
    impact = quote.get("price_impact_pct")
    gross_mid = quote.get("mid")
    # Net mid estimate: apply fee_bps only when API returned it (labeled).
    net_mid = None
    if isinstance(gross_mid, (int, float)) and isinstance(fee_bps, (int, float)):
        net_mid = float(gross_mid) * (1.0 - float(fee_bps) / 10_000.0)
    return {
        "gross_mid": gross_mid,
        "net_mid_after_fee_bps": net_mid,
        "fee_bps": fee_bps,
        "fee_bps_label": "API_feeBps" if fee_bps is not None else "unavailable",
        "slippage_bps": slip,
        "slippage_bps_label": "API_slippageBps" if slip is not None else "unavailable",
        "price_impact_pct": impact,
        "prioritization_fee_lamports": prio,
        "prioritization_fee_label": quote.get("prioritization_fee_label"),
        "note": (
            "gross=out/in mid from quote; net applies API feeBps only when present; "
            "priority fee is labeled ESTIMATE from API field or unavailable — not invented"
        ),
    }


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(
        description=(
            "Solana Jupiter research tape (quote-only). "
            "GET api.jup.ag/swap/v2/order WITHOUT taker. Never sign/send."
        )
    )
    p.add_argument(
        "--live",
        action="store_true",
        help="Hard-refused — Solana live/custody not wired",
    )
    p.add_argument(
        "--amount",
        default="100000000",
        help="Input amount in raw units (default 0.1 SOL = 100000000 lamports)",
    )
    p.add_argument("--input-mint", default=SOL_MINT, help="Input mint (default SOL)")
    p.add_argument("--output-mint", default=USDC_MINT, help="Output mint (default USDC)")
    p.add_argument("--slippage-bps", type=int, default=None, help="Optional slippageBps")
    p.add_argument("--timeout", type=float, default=10.0, help="HTTP timeout seconds")
    p.add_argument(
        "--fixture",
        action="store_true",
        help="Use fixture quote (requires --allow-fixture)",
    )
    p.add_argument(
        "--allow-fixture",
        action="store_true",
        help="Permit fixture mode (offline tests only; default OFF)",
    )
    p.add_argument(
        "--price-v3",
        action="store_true",
        help="Also fetch Jupiter Price V3 USD for input mint",
    )
    args = p.parse_args(argv)

    if args.live:
        print(json.dumps(_refuse_live(), indent=2, sort_keys=True))
        return 2

    out: dict[str, Any] = {
        "ok": True,
        "mode": "research_dry_run",
        "live": False,
        "signed": False,
        "execution": "quote_only",
        "api": {
            "order": "GET https://api.jup.ag/swap/v2/order (no taker)",
            "price": "GET https://api.jup.ag/price/v3",
            "docs_order": "https://developers.jup.ag/docs/swap/order-and-execute",
            "docs_price": "https://developers.jup.ag/docs/price",
            "portal": "https://developers.jup.ag/portal",
            "auth": "optional x-api-key via JUPITER_API_KEY; keyless low RPS",
        },
        "errors": [],
        "allow_fixture": bool(args.allow_fixture),
    }

    if args.fixture and not args.allow_fixture:
        out["ok"] = False
        out["errors"].append(
            {
                "error": "fixture requires --allow-fixture (no silent fixture)",
                "kill_reason": "fixture_without_allow",
            }
        )
        print(json.dumps(out, indent=2, sort_keys=True))
        return 1

    try:
        q = fetch_jupiter_order_quote(
            input_mint=args.input_mint,
            output_mint=args.output_mint,
            amount=args.amount,
            slippage_bps=args.slippage_bps,
            timeout=args.timeout,
            allow_fixture=bool(args.allow_fixture),
            use_fixture=bool(args.fixture),
        )
        brief = q.to_dict()
        out["quote"] = brief
        out["mid"] = brief.get("mid")
        out["out_amount"] = brief.get("out_amount")
        out["in_amount"] = brief.get("in_amount")
        out["price_impact_pct"] = brief.get("price_impact_pct")
        out["route_labels"] = brief.get("route_labels")
        out["gross_vs_net"] = _gross_vs_net(brief)
        out["tape"] = [q.to_tape_quote().to_dict()]
    except JupiterQuoteError as e:
        out["ok"] = False
        out["errors"].append({"venue": "jupiter_solana", "error": str(e)})
    except Exception as e:
        out["ok"] = False
        out["errors"].append({"venue": "jupiter_solana", "error": f"{type(e).__name__}: {e}"})

    if args.price_v3:
        try:
            px = fetch_jupiter_usd_price(
                args.input_mint,
                timeout=args.timeout,
                allow_fixture=bool(args.allow_fixture),
                use_fixture=bool(args.fixture),
            )
            out["price_v3"] = px.to_dict()
            out.setdefault("tape", []).append(px.to_dict())
        except Exception as e:
            out["errors"].append({"venue": "jupiter_price_v3", "error": str(e)})
            # Price V3 failure does not invent a price; leave ok if quote succeeded
            if "quote" not in out:
                out["ok"] = False

    print(json.dumps(out, indent=2, sort_keys=True))
    return 0 if out["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
