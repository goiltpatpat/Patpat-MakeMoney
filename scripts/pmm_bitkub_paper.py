#!/usr/bin/env python3
"""Bitkub PAPER round-trip CLI — public ticker only; never places live orders."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from venues.bitkub.paper import (  # noqa: E402
    BitkubPaperError,
    LIVE_GATE_ENV,
    DEFAULT_STAKE_THB,
    DEFAULT_SYMBOL,
    default_runtime_dir,
    load_day_caps,
    paper_round_trip,
    refuse_live,
    simulate_paper_order,
)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Bitkub paper open+close round-trip (public ticker only; no live orders)."
    )
    p.add_argument("--symbol", default=DEFAULT_SYMBOL, help="THB pair, default BTC_THB")
    p.add_argument("--stake-thb", type=float, default=DEFAULT_STAKE_THB, help="Paper stake in THB")
    p.add_argument("--timeout", type=float, default=8.0)
    p.add_argument(
        "--runtime-dir",
        type=Path,
        default=None,
        help="Runtime dir for day caps/state (default: <repo>/runtime)",
    )
    p.add_argument("--no-caps", action="store_true", help="Skip day-cap enforcement (still paper)")
    p.add_argument("--no-record", action="store_true", help="Do not update day state file")
    p.add_argument(
        "--single",
        choices=("buy", "sell"),
        help="Single paper fill instead of round-trip (still paper-only)",
    )
    p.add_argument(
        "--live",
        action="store_true",
        help="REFUSED: live Bitkub orders are not implemented",
    )
    args = p.parse_args(argv)

    # Hard refuse live — env gate alone is insufficient and also not honored.
    if args.live or os.environ.get(LIVE_GATE_ENV, "").strip() in ("1", "true", "yes"):
        if args.live:
            try:
                refuse_live()
            except BitkubPaperError as e:
                print(json.dumps({"ok": False, "live": False, "error": str(e)}, indent=2))
                return 2
        # Env set without --live: still paper-only; warn in payload later.

    runtime_dir = args.runtime_dir or default_runtime_dir(ROOT)

    try:
        if args.single:
            fill = simulate_paper_order(
                side=args.single,
                symbol=args.symbol,
                timeout=args.timeout,
                stake_thb=args.stake_thb,
            )
            out = {"ok": True, "mode": "paper", "live": False, "fill": fill}
        else:
            # Ensure caps file exists for desk visibility
            load_day_caps(runtime_dir)
            out = paper_round_trip(
                symbol=args.symbol,
                stake_thb=args.stake_thb,
                timeout=args.timeout,
                runtime_dir=runtime_dir,
                enforce_caps=not args.no_caps,
                record=not args.no_record,
            )
        if os.environ.get(LIVE_GATE_ENV, "").strip() in ("1", "true", "yes"):
            out["live_gate_note"] = (
                f"{LIVE_GATE_ENV} is set but live orders remain unimplemented; paper path used."
            )
        print(json.dumps(out, indent=2, sort_keys=True))
        return 0
    except BitkubPaperError as e:
        print(json.dumps({"ok": False, "mode": "paper", "live": False, "error": str(e)}, indent=2))
        return 1


if __name__ == "__main__":
    sys.exit(main())
