#!/usr/bin/env python3
"""Patpat-MakeMoney multi-venue tape CLI — JSON brief for Ledger (read-only)."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Multi-venue public tape brief (no execution).")
    p.add_argument("--btc", action="store_true", help="Include public BTCUSDT (Binance).")
    p.add_argument("--btc-mark", action="store_true", help="Prefer Binance mark price for BTC.")
    p.add_argument("--oneinch", action="store_true", help="Include 1inch WBTC-USD (fixture if no key).")
    p.add_argument("--bitkub", action="store_true", help="Include Bitkub public BTC_THB ticker.")
    p.add_argument("--bitkub-paper", choices=("buy", "sell"), help="Also simulate Bitkub paper fill side.")
    p.add_argument("--timeout", type=float, default=8.0, help="HTTP timeout seconds.")
    p.add_argument("--all", action="store_true", help="btc + oneinch + bitkub.")
    args = p.parse_args(argv)

    if args.all:
        args.btc = True
        args.oneinch = True
        args.bitkub = True
    if not (args.btc or args.btc_mark or args.oneinch or args.bitkub or args.bitkub_paper):
        args.btc = True  # default: public BTC only

    out: dict = {"ok": True, "tape": [], "errors": [], "mode": "read_only"}

    if args.btc or args.btc_mark:
        try:
            from venues.public_btc import fetch_public_btc

            prefer = "mark" if args.btc_mark else "last"
            q = fetch_public_btc(prefer=prefer, timeout=args.timeout)
            out["tape"].append(q.to_dict())
        except Exception as e:
            out["ok"] = False
            out["errors"].append({"venue": "binance_public", "error": str(e)})

    if args.oneinch:
        try:
            from venues.oneinch_quotes import fetch_wbtc_usd_quote

            q = fetch_wbtc_usd_quote(timeout=args.timeout, allow_fixture=True)
            out["tape"].append(q.to_dict())
        except Exception as e:
            out["ok"] = False
            out["errors"].append({"venue": "oneinch", "error": str(e)})

    if args.bitkub or args.bitkub_paper:
        try:
            from venues.bitkub.paper import (
                fetch_public_ticker,
                simulate_paper_order,
                ticker_to_tape_quote,
            )

            row = fetch_public_ticker("BTC_THB", timeout=args.timeout)
            out["tape"].append(ticker_to_tape_quote(row, symbol="BTC_THB").to_dict())
            if args.bitkub_paper:
                out["bitkub_paper"] = simulate_paper_order(
                    side=args.bitkub_paper,
                    symbol="BTC_THB",
                    ticker_row=row,
                )
        except Exception as e:
            out["ok"] = False
            out["errors"].append({"venue": "bitkub_public", "error": str(e)})

    print(json.dumps(out, indent=2, sort_keys=True))
    return 0 if out["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
