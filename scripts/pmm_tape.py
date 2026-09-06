#!/usr/bin/env python3
"""Patpat-MakeMoney multi-venue tape CLI — JSON brief for Ledger (read-only)."""
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


def _fetch_usdthb(timeout: float) -> Optional[dict[str, Any]]:
    """Optional labeled public USDTHB (Binance). Never invent FX if fetch fails."""
    import urllib.error
    import urllib.parse
    import urllib.request
    from datetime import datetime, timezone

    url = "https://api.binance.com/api/v3/ticker/price?" + urllib.parse.urlencode(
        {"symbol": "USDTTHB"}
    )
    # USDTTHB is THB per 1 USDT ≈ USDTHB for desk labeling
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Patpat-MakeMoney/venues-usdthb",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        px = float(data["price"])
        if px <= 0:
            return None
        return {
            "pair": "USDTTHB",
            "symbol": "USDTTHB",
            "price": px,
            "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "source": "binance_ticker_price_USDTTHB",
            "note": "labeled public USDTTHB used as USDTHB proxy — not invented",
        }
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Multi-venue public tape brief (no execution).")
    p.add_argument("--btc", action="store_true", help="Include public BTCUSDT (Binance).")
    p.add_argument("--btc-mark", action="store_true", help="Prefer Binance mark price for BTC.")
    p.add_argument("--oneinch", action="store_true", help="Include 1inch WBTC-USD (fixture if no key).")
    p.add_argument("--bitkub", action="store_true", help="Include Bitkub public BTC_THB ticker.")
    p.add_argument("--bitkub-paper", choices=("buy", "sell"), help="Also simulate Bitkub paper fill side.")
    p.add_argument("--timeout", type=float, default=8.0, help="HTTP timeout seconds.")
    p.add_argument("--all", action="store_true", help="btc + oneinch + bitkub.")
    p.add_argument(
        "--divergence",
        action="store_true",
        help="Emit triple-tape divergence block (same-currency numeric; cross=unit_mismatch).",
    )
    p.add_argument(
        "--usdthb",
        action="store_true",
        help="Fetch labeled public USDTTHB (Binance) for optional FX-adjusted cross compares.",
    )
    args = p.parse_args(argv)

    if args.all:
        args.btc = True
        args.oneinch = True
        args.bitkub = True
    if args.divergence and not (args.btc or args.btc_mark or args.oneinch or args.bitkub or args.bitkub_paper):
        # Divergence implies we want the triple tape
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

    usdthb = None
    if args.usdthb or (args.divergence and args.usdthb):
        usdthb = _fetch_usdthb(args.timeout)
        if usdthb is None:
            out["errors"].append(
                {
                    "venue": "usdthb",
                    "error": "USDTTHB fetch failed — cross-currency stays unit_mismatch (no invented FX)",
                }
            )

    if args.divergence:
        from venues.divergence import compute_triple_tape_divergence

        # If --usdthb not requested, do not invent; leave usdthb=None
        fx = usdthb if args.usdthb else None
        out["divergence"] = compute_triple_tape_divergence(out["tape"], usdthb=fx)

    print(json.dumps(out, indent=2, sort_keys=True))
    return 0 if out["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
