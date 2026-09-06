#!/usr/bin/env python3
"""Solana PAPER fill CLI — Jupiter quote → paper fill stub → optional edge_log.

Never signs or broadcasts. --live hard-refused. Fixture only with --allow-fixture.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
SCRIPTS = ROOT / "scripts"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from venues.solana.jupiter_quotes import SOL_MINT, USDC_MINT  # noqa: E402
from venues.solana.paper import (  # noqa: E402
    DEFAULT_AMOUNT,
    LIVE_GATE_ENV,
    VENUE,
    SolanaPaperError,
    paper_batch_fills,
    refuse_live,
    simulate_paper_fill,
)

import pmm_edge_log  # noqa: E402


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(
        description=(
            "Solana paper fill from Jupiter quote (no sign/send). "
            "Optional --log-edge writes scorecard-readable edge_log rows."
        )
    )
    p.add_argument("--live", action="store_true", help="REFUSED: Solana live not implemented")
    p.add_argument("--side", choices=("buy", "sell"), default="buy")
    p.add_argument(
        "--amount",
        default=DEFAULT_AMOUNT,
        help="Input amount in raw units (default 0.001 SOL = 1000000 lamports)",
    )
    p.add_argument("--input-mint", default=SOL_MINT)
    p.add_argument("--output-mint", default=USDC_MINT)
    p.add_argument("--slippage-bps", type=int, default=None)
    p.add_argument("--timeout", type=float, default=10.0)
    p.add_argument("--fixture", action="store_true", help="Use fixture quote (requires --allow-fixture)")
    p.add_argument(
        "--allow-fixture",
        action="store_true",
        help="Permit fixture mode (offline tests only; default OFF)",
    )
    p.add_argument(
        "--batch",
        type=int,
        default=0,
        help="Emit N paper fills from one quote (for edge_log proof; default 0 = single)",
    )
    p.add_argument(
        "--log-edge",
        action="store_true",
        help="Append paper fills to runtime/edge_log.jsonl via pmm_edge_log",
    )
    p.add_argument(
        "--log",
        type=Path,
        default=None,
        help="edge_log.jsonl path (default: runtime/edge_log.jsonl)",
    )
    args = p.parse_args(argv)

    if args.live:
        try:
            refuse_live()
        except SolanaPaperError as e:
            print(json.dumps({"ok": False, "live": False, "error": str(e)}, indent=2, sort_keys=True))
            return 2

    if args.fixture and not args.allow_fixture:
        print(
            json.dumps(
                {
                    "ok": False,
                    "live": False,
                    "mode": "paper",
                    "error": "fixture requires --allow-fixture (no silent fixture)",
                    "kill_reason": "fixture_without_allow",
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 1

    try:
        if args.batch and args.batch > 0:
            out = paper_batch_fills(
                args.batch,
                side=args.side,
                amount=args.amount,
                allow_fixture=bool(args.allow_fixture),
                use_fixture=bool(args.fixture),
                timeout=float(args.timeout),
            )
        else:
            fill = simulate_paper_fill(
                side=args.side,
                amount=args.amount,
                input_mint=args.input_mint,
                output_mint=args.output_mint,
                slippage_bps=args.slippage_bps,
                timeout=float(args.timeout),
                allow_fixture=bool(args.allow_fixture),
                use_fixture=bool(args.fixture),
            )
            out = {
                "ok": True,
                "mode": "paper",
                "live": False,
                "venue": VENUE,
                "fill": fill,
                "realized_pnl_thb": None,
                "pnl_basis": None,
                "note": fill.get("note"),
            }
        if os.environ.get(LIVE_GATE_ENV, "").strip() in ("1", "true", "yes"):
            out["live_gate_note"] = (
                f"{LIVE_GATE_ENV} is set but live swaps remain unimplemented; paper path used."
            )

        if args.log_edge:
            log_path = args.log or (ROOT / "runtime" / "edge_log.jsonl")
            logged = pmm_edge_log.append_edge_log(out, log_path=log_path, source="solana_paper")
            out["edge_log"] = {
                "ok": logged["ok"],
                "written": logged["written"],
                "log_path": logged["log_path"],
            }

        print(json.dumps(out, indent=2, sort_keys=True))
        return 0
    except SolanaPaperError as e:
        print(
            json.dumps(
                {"ok": False, "mode": "paper", "live": False, "venue": VENUE, "error": str(e)},
                indent=2,
                sort_keys=True,
            )
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
