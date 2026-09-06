#!/usr/bin/env python3
"""Bitkub ↔ Binance TH same-currency THB basis SCANNER — paper/read-only; --live hard-refused.

Ledger JSON (and optional JSONL) with mids, abs/bps spread, fee floor, duration filter.
Sources: Bitkub public ticker + api.binance.th ONLY. No FX. No live orders.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from venues.basis.bitkub_bnth import (  # noqa: E402
    BasisFeeConfig,
    DEFAULT_BITKUB_SYMBOL,
    DEFAULT_BNTH_SYMBOL,
    opportunity_persisted,
    scan_bitkub_bnth_basis,
)

DEFAULT_LEDGER = ROOT / "runtime" / "basis_ledger.jsonl"


def _refuse_live() -> dict[str, Any]:
    return {
        "ok": False,
        "live": False,
        "error": (
            "REFUSED: --live is not implemented for Bitkub↔BNTH basis. "
            "Paper/read-only scan only — no orders."
        ),
        "mode": "paper",
        "execution": "scan_only",
    }


def _env_allow_fixture() -> bool:
    return os.environ.get("PMM_BASIS_ALLOW_FIXTURE", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def _append_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, sort_keys=True) + "\n")


def _prices_only(opp: dict[str, Any]) -> dict[str, Any]:
    """Compact view: prices / bps only (for dry-run sample reports)."""
    legs = opp.get("legs") or {}
    bk = legs.get("bitkub") or {}
    bn = legs.get("bnth") or {}
    return {
        "bitkub_mid": bk.get("price"),
        "bnth_mid": bn.get("price"),
        "gross_basis_bps": opp.get("gross_basis_bps"),
        "net_basis_bps": opp.get("net_basis_bps"),
        "fee_floor_bps": opp.get("fee_floor_bps"),
        "direction": opp.get("direction"),
        "kill": opp.get("kill"),
        "kill_reason": opp.get("kill_reason"),
        "soft_flags": opp.get("soft_flags"),
        "opportunity": opp.get("opportunity"),
        "status": opp.get("status"),
    }


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(
        description=(
            "Bitkub↔BNTH same-ccy THB basis SCANNER (paper/read-only). "
            "api.binance.th only. Shows gross vs net after labeled taker fee haircuts. "
            "--live hard-refused."
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
        help="REFUSED: live basis / orders are not implemented",
    )
    p.add_argument("--bitkub-symbol", default=DEFAULT_BITKUB_SYMBOL)
    p.add_argument("--bnth-symbol", default=DEFAULT_BNTH_SYMBOL)
    p.add_argument("--timeout", type=float, default=8.0)
    p.add_argument(
        "--bitkub-taker-bps",
        type=float,
        default=25.0,
        help="Labeled Bitkub taker fee estimate (bps)",
    )
    p.add_argument(
        "--bnth-taker-bps",
        type=float,
        default=10.0,
        help="Labeled BNTH taker fee estimate (bps)",
    )
    p.add_argument(
        "--min-net-bps",
        type=float,
        default=0.0,
        help="Minimum |net_basis_bps| to mark opportunity",
    )
    p.add_argument(
        "--max-age-sec",
        type=float,
        default=30.0,
        help="Kill as stale if either quote age exceeds this",
    )
    p.add_argument(
        "--fixture",
        action="store_true",
        help="Use fixture mids (offline / tests; killed unless --allow-fixture)",
    )
    p.add_argument(
        "--allow-fixture",
        action="store_true",
        help=(
            "Permit fixture mids in opportunity output (OFFLINE TESTS ONLY). "
            "Also via env PMM_BASIS_ALLOW_FIXTURE=1."
        ),
    )
    p.add_argument(
        "--poll",
        type=float,
        default=0.0,
        help="Poll interval seconds (0 = single sample)",
    )
    p.add_argument(
        "--persist-sec",
        type=float,
        default=0.0,
        help="With --poll: require |net|>=min-net for this many seconds before persisted=true",
    )
    p.add_argument(
        "--min-persist-sec",
        type=float,
        default=None,
        help="Alias of --persist-sec (duration filter)",
    )
    p.add_argument(
        "--min-persist-samples",
        type=int,
        default=0,
        help="Require N consecutive qualifying samples (alternative to --persist-sec)",
    )
    p.add_argument(
        "--max-polls",
        type=int,
        default=1,
        help="Max poll iterations when --poll > 0 (default 1 = single)",
    )
    p.add_argument(
        "--log",
        action="store_true",
        help=f"Append each sample to {DEFAULT_LEDGER}",
    )
    p.add_argument(
        "--ledger",
        type=Path,
        default=DEFAULT_LEDGER,
        help="JSONL ledger path when --log",
    )
    p.add_argument(
        "--prices-only",
        action="store_true",
        help="Print compact prices/bps view only",
    )
    args = p.parse_args(argv)

    if args.live:
        print(json.dumps(_refuse_live(), indent=2, sort_keys=True))
        return 2

    allow_fixture = bool(args.allow_fixture) or _env_allow_fixture()
    persist_sec = (
        float(args.min_persist_sec)
        if args.min_persist_sec is not None
        else float(args.persist_sec)
    )
    fees = BasisFeeConfig(
        bitkub_taker_bps=args.bitkub_taker_bps,
        bnth_taker_bps=args.bnth_taker_bps,
        min_net_bps=args.min_net_bps,
    )

    poll = float(args.poll)
    max_polls = int(args.max_polls)
    if poll <= 0:
        max_polls = 1
    elif max_polls < 1:
        max_polls = 1

    min_samples = int(args.min_persist_samples)
    if min_samples <= 0 and persist_sec > 0 and poll > 0:
        min_samples = max(1, int(math.ceil(persist_sec / poll)))

    if poll > 0 and persist_sec > 0:
        need = max(1, int(math.ceil(persist_sec / poll)))
        if max_polls < need:
            max_polls = need

    history: list[dict[str, Any]] = []
    last_out: dict[str, Any] = {}

    for i in range(max_polls):
        opp = scan_bitkub_bnth_basis(
            bitkub_symbol=args.bitkub_symbol,
            bnth_symbol=args.bnth_symbol,
            timeout=args.timeout,
            fees=fees,
            allow_fixture=allow_fixture,
            use_fixture=args.fixture,
            max_age_sec=args.max_age_sec,
        )
        history.append(opp)
        if args.log:
            _append_jsonl(Path(args.ledger), opp)

        persist_info: Optional[dict[str, Any]] = None
        if min_samples > 0:
            persist_info = opportunity_persisted(
                history,
                min_samples=min_samples,
                threshold_bps=args.min_net_bps,
            )
        elif persist_sec > 0 and poll <= 0:
            persist_info = {
                "persisted": False,
                "reason": "need_poll",
                "note": (
                    "--persist-sec/--min-persist-sec requires --poll to accumulate samples"
                ),
            }

        last_out = {
            "ok": True,
            "mode": "paper",
            "live": False,
            "paper": True,
            "allow_fixture": allow_fixture,
            "sample": i + 1,
            "samples": len(history),
            "thesis": (
                "Bitkub↔BNTH same-ccy THB basis only; gross vs net_basis_bps with labeled "
                "fee haircuts; sources bitkub + api.binance.th; kill fixture/binance.com/FX; "
                "--live refuse; Ledger JSON/JSONL"
            ),
            "basis": opp,
            "persist": persist_info,
            "prices": _prices_only(opp),
        }

        if persist_info and persist_info.get("persisted") and persist_sec > 0:
            break
        if poll > 0 and i + 1 < max_polls:
            time.sleep(poll)

    if args.prices_only:
        print(json.dumps(last_out.get("prices") or {}, indent=2, sort_keys=True))
    else:
        print(json.dumps(last_out, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
