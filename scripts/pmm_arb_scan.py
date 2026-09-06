#!/usr/bin/env python3
"""DEX→CEX arb SCANNER CLI — paper/read-only only; --live hard-refused.

Prints Ledger JSON opportunities (gross vs net after fee/latency/Travel Rule buffers).
No live orders. No auto-transfer execution.
"""
from __future__ import annotations

import argparse
import os
import json
import sys
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from venues.arb.dex_cex import (  # noqa: E402
    ArbFeeConfig,
    detect_dex_cex_opportunity,
    simulate_paper_dual_leg,
)
from venues.binance_th.tape import (  # noqa: E402
    BinanceTHError,
    DEFAULT_SYMBOL as BNTH_SYMBOL,
    fetch_public_ticker,
    fetch_usdtthb_fx,
    ticker_to_tape_quote,
    unavailable_status,
)
from venues.bitkub import paper as bitkub_paper  # noqa: E402
from venues import oneinch_quotes  # noqa: E402


def _refuse_live() -> dict[str, Any]:
    return {
        "ok": False,
        "live": False,
        "error": (
            "REFUSED: --live is not implemented for DEX→CEX arb. "
            "Paper/read-only scan only — no orders, no auto-transfer."
        ),
        "mode": "paper",
        "execution": "scan_only",
    }


def _env_allow_fixture() -> bool:
    return os.environ.get("PMM_ARB_ALLOW_FIXTURE", "").strip().lower() in ("1", "true", "yes")


def _load_dex_mid(*, fixture: bool, allow_fixture: bool, timeout: float) -> dict[str, Any]:
    """Load DEX mid. Money-path default: never silent 1inch fixture (allow_fixture=False)."""
    if fixture:
        return oneinch_quotes.fixture_wbtc_usd_quote().to_dict()
    # Default money-path: require key / live quote; no silent fixture fallback
    q = oneinch_quotes.fetch_wbtc_usd_quote(allow_fixture=False, timeout=timeout)
    return q.to_dict()


def _load_binance_th_mid(
    symbol: str,
    *,
    fixture: bool,
    timeout: float,
) -> dict[str, Any]:
    try:
        row = fetch_public_ticker(symbol, timeout=timeout, use_fixture=fixture)
        return ticker_to_tape_quote(row, symbol=symbol).to_dict()
    except BinanceTHError as e:
        if fixture:
            row = fetch_public_ticker(symbol, use_fixture=True)
            return ticker_to_tape_quote(row, symbol=symbol).to_dict()
        status = unavailable_status(reason=str(e))
        raise BinanceTHError(json.dumps(status)) from e


def _load_bitkub_mid(symbol: str = "BTC_THB", *, timeout: float) -> dict[str, Any]:
    row = bitkub_paper.fetch_public_ticker(symbol, timeout=timeout)
    return bitkub_paper.ticker_to_tape_quote(row, symbol=symbol).to_dict()


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(
        description=(
            "DEX→CEX arb SCANNER (paper/read-only). Binance TH via api.binance.th only. "
            "Shows gross vs net with fee stack + transfer latency + Travel Rule buffers."
        )
    )
    p.add_argument(
        "--paper",
        action="store_true",
        default=True,
        help="Paper/read-only scan (default; only supported mode)",
    )
    p.add_argument(
        "--live",
        action="store_true",
        help="REFUSED: live arb / auto-transfer is not implemented",
    )
    p.add_argument(
        "--cex",
        choices=("binance_th", "bitkub"),
        default="binance_th",
        help="CEX leg (default: binance_th — second TH lane, does not replace Bitkub)",
    )
    p.add_argument("--bnth-symbol", default=BNTH_SYMBOL, help="Binance TH symbol, default BTCTHB")
    p.add_argument("--bitkub-symbol", default="BTC_THB")
    p.add_argument("--fixture", action="store_true", help="Use fixture mids (offline / tests)")
    p.add_argument(
        "--allow-fixture",
        action="store_true",
        help=(
            "Permit fixture mids in opportunity output (OFFLINE TESTS ONLY). "
            "Default OFF: fixture legs are KILLed and never claim net>0. "
            "Also honored via env PMM_ARB_ALLOW_FIXTURE=1."
        ),
    )
    p.add_argument(
        "--no-fetch-usdthb",
        action="store_true",
        help="Do not auto-fetch labeled USDTTHB from api.binance.th when --usdthb omitted",
    )
    p.add_argument("--timeout", type=float, default=8.0)
    p.add_argument("--dex-fee-bps", type=float, default=30.0)
    p.add_argument("--cex-fee-bps", type=float, default=10.0)
    p.add_argument("--withdraw-fee-bps", type=float, default=5.0)
    p.add_argument(
        "--transfer-time-penalty-bps",
        type=float,
        default=15.0,
        help="Labeled ESTIMATE deposit-latency buffer (not measured fact)",
    )
    p.add_argument(
        "--travel-rule-buffer-bps",
        type=float,
        default=10.0,
        help="Labeled ESTIMATE Travel Rule / KYC friction buffer",
    )
    p.add_argument(
        "--usdthb",
        type=float,
        default=None,
        help="Labeled public USDTHB (THB per 1 USD). Required for DEX-USD vs CEX-THB compare. Never invented.",
    )
    p.add_argument(
        "--usdthb-source",
        default="cli_labeled",
        help="Label for --usdthb source (required honesty tag)",
    )
    p.add_argument(
        "--simulate-paper-fills",
        action="store_true",
        help="Optional: simulate dual-leg paper fills (no orders) for edge_log tagging",
    )
    p.add_argument("--size", type=float, default=0.001, help="Paper dual-leg size (base units)")
    args = p.parse_args(argv)

    if args.live:
        print(json.dumps(_refuse_live(), indent=2, sort_keys=True))
        return 2

    fees = ArbFeeConfig(
        dex_fee_bps=args.dex_fee_bps,
        cex_fee_bps=args.cex_fee_bps,
        withdraw_fee_bps=args.withdraw_fee_bps,
        transfer_time_penalty_bps=args.transfer_time_penalty_bps,
        travel_rule_buffer_bps=args.travel_rule_buffer_bps,
    )

    allow_fixture = bool(args.allow_fixture) or _env_allow_fixture()

    usdthb = None
    if args.usdthb is not None:
        if args.usdthb <= 0:
            print(
                json.dumps(
                    {"ok": False, "error": "usdthb must be > 0 when provided"},
                    indent=2,
                )
            )
            return 1
        usdthb = {
            "price": float(args.usdthb),
            "source": args.usdthb_source,
            "pair": "USDTHB",
            "note": "labeled FX quote — not invented",
        }
    elif not args.no_fetch_usdthb:
        # Prefer labeled public USDTTHB from api.binance.th — never invent
        try:
            usdthb = fetch_usdtthb_fx(timeout=args.timeout, use_fixture=args.fixture)
        except BinanceTHError:
            usdthb = None

    try:
        dex = _load_dex_mid(
            fixture=args.fixture, allow_fixture=allow_fixture, timeout=args.timeout
        )
        if args.cex == "binance_th":
            cex = _load_binance_th_mid(
                args.bnth_symbol, fixture=args.fixture, timeout=args.timeout
            )
        else:
            if args.fixture:
                # Bitkub has no built-in fixture; use a synthetic labeled mid for offline
                cex = {
                    "venue": "bitkub_public",
                    "symbol": args.bitkub_symbol,
                    "price": 2600000.0,
                    "ts": dex.get("ts"),
                    "source": "fixture",
                }
            else:
                cex = _load_bitkub_mid(args.bitkub_symbol, timeout=args.timeout)
    except (BinanceTHError, bitkub_paper.BitkubPaperError, oneinch_quotes.OneInchQuoteError) as e:
        # Try parse unavailable JSON from BinanceTHError
        err_payload: dict[str, Any]
        try:
            err_payload = json.loads(str(e))
        except json.JSONDecodeError:
            err_payload = {"error": str(e)}
        print(
            json.dumps(
                {"ok": False, "mode": "paper", "live": False, **err_payload},
                indent=2,
                sort_keys=True,
            )
        )
        return 1

    opp = detect_dex_cex_opportunity(
        dex, cex, fees=fees, usdthb=usdthb, allow_fixture=allow_fixture
    )
    out: dict[str, Any] = {
        "ok": True,
        "mode": "paper",
        "live": False,
        "paper": True,
        "allow_fixture": allow_fixture,
        "cex_lane": args.cex,
        "thesis": (
            "BNTH is second TH lane (does not replace Bitkub until pass); "
            "arb detector shows gross vs net with fee stack + non-zero latency buffer "
            "+ Travel Rule buffer; kill inventing FX; --live hard-refuse"
        ),
        "opportunity": opp,
    }

    if args.simulate_paper_fills:
        out["paper_dual_leg"] = simulate_paper_dual_leg(opp, size=args.size)

    print(json.dumps(out, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
