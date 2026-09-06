"""Optional thin Solana (Jupiter) quote vs BNTH USDT-ish compare (paper/research).

Same hygiene as dex_cex: kill unit_mismatch; kill money-leg source=fixture unless
allow_fixture. Only compare with labeled FX or same-stable path (USDC≈USDT labeled).
Never invents FX. No live swaps.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from venues.arb.dex_cex import ArbFeeConfig, detect_dex_cex_opportunity


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sol_quote_to_dex_leg(quote: dict[str, Any]) -> dict[str, Any]:
    """Map JupiterOrderQuote.to_dict() / tape mid into a dex-leg dict for detect_*."""
    mid = quote.get("mid", quote.get("price"))
    if mid is None:
        raise ValueError("sol quote missing mid/price")
    src = quote.get("source") or "jupiter_swap_v2_order"
    return {
        "venue": quote.get("venue") or "jupiter_solana",
        "symbol": quote.get("symbol") or "SOL/USDC",
        "price": float(mid),
        "ts": quote.get("ts") or _utc_now_iso(),
        "source": src,
        "quote_ccy_hint": "USD",  # USDC treated as USD-stable for desk label
        "out_amount": quote.get("out_amount"),
        "price_impact_pct": quote.get("price_impact_pct"),
        "note": "Solana Jupiter research mid; USDC labeled USD-stable — not THB",
    }


def detect_sol_vs_bnth(
    sol_quote: dict[str, Any],
    bnth_quote: dict[str, Any],
    *,
    fees: Optional[ArbFeeConfig] = None,
    usdthb: Optional[dict[str, Any]] = None,
    usdt_usdc_one_to_one: bool = False,
    allow_fixture: bool = False,
) -> dict[str, Any]:
    """
    Compare Solana Jupiter mid vs BNTH CEX mid.

    - Same-stable path: set usdt_usdc_one_to_one=True to label USDC≈USDT (explicit).
    - Else supply labeled usdthb for cross THB, or expect unit_mismatch kill.
    - Fixture legs kill unless allow_fixture (hygiene parity with dex_cex).
    """
    dex = sol_quote_to_dex_leg(sol_quote)
    cex = {
        "venue": bnth_quote.get("venue") or "binance_th",
        "symbol": str(bnth_quote.get("symbol") or ""),
        "price": float(bnth_quote["price"]),
        "ts": bnth_quote.get("ts"),
        "source": bnth_quote.get("source"),
    }

    # For SOL/USDC vs BNTH SOLUSDT (or similar): rewrite symbols to USD-ish
    # so divergence quote_currency sees USD when same-stable path is opted in.
    if usdt_usdc_one_to_one:
        dex = dict(dex)
        cex = dict(cex)
        dex["symbol"] = "SOL-USD"
        # Map USDT books to USD label for compare; explicit approximation.
        sym = cex["symbol"].upper().replace("_", "")
        if sym.endswith("USDT") or sym.endswith("USDC"):
            cex["symbol"] = "SOL-USD"
        fx_note = {
            "pair": "USDC_USDT",
            "price": 1.0,
            "source": "labeled_same_stable_usdc_usdt_one_to_one",
            "note": "EXPLICIT labeled USDC≈USDT — not invented silent FX",
            "ts": _utc_now_iso(),
        }
        # detect_dex_cex uses usdthb for THB; for USD-USD we don't need it.
        # Pass through as annotation only.
        out = detect_dex_cex_opportunity(
            dex, cex, fees=fees, usdthb=None, allow_fixture=allow_fixture
        )
        out["same_stable_path"] = fx_note
        out["lane"] = "solana_vs_bnth"
        out["note"] = (
            (out.get("note") or "")
            + "; sol_cex stub: Jupiter vs BNTH with labeled USDC≈USDT same-stable path"
        )
        return out

    out = detect_dex_cex_opportunity(
        dex, cex, fees=fees, usdthb=usdthb, allow_fixture=allow_fixture
    )
    out["lane"] = "solana_vs_bnth"
    out["same_stable_path"] = None
    if out.get("kill_reason") == "unit_mismatch":
        out["note"] = (
            (out.get("note") or "")
            + "; sol_cex: pass usdt_usdc_one_to_one=True for USDC≈USDT or labeled usdthb for THB"
        )
    return out
