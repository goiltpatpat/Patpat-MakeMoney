#!/usr/bin/env python3
"""Jupiter quote-dispersion SCANNER (T1-plus) — paper/RO; --live refused.

Size-ladder Jupiter /order quote-only mids + fee/slip stack; optional
Raydium/Orca/Meteora RO pool mids (deferred when blocked). Fixture-kill
default. Never invents mids. No tips, secrets, or auto-trade.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from venues.solana.quote_dispersion import (  # noqa: E402
    DEFAULT_SIZE_LADDER_LAMPORTS,
    DispersionError,
    scan_quote_dispersion,
)

DEFAULT_LEDGER = ROOT / "runtime" / "quote_dispersion_ledger.jsonl"


def _refuse_live() -> dict[str, Any]:
    return {
        "ok": False,
        "live": False,
        "error": (
            "REFUSED: --live is not implemented for quote-dispersion. "
            "Paper/read-only scan only — no swaps, no seeds, no tips, no auto-trade."
        ),
        "mode": "paper",
        "execution": "scan_only",
        "lane": "jupiter_quote_dispersion",
    }


def _env_allow_fixture() -> bool:
    return os.environ.get("PMM_QUOTE_DISPERSION_ALLOW_FIXTURE", "").strip().lower() in (
        "1",
        "true",
        "yes",
    ) or os.environ.get("PMM_SOL_ALLOW_FIXTURE", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def _append_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, sort_keys=True) + "\n")


def _compact(scan: dict[str, Any]) -> dict[str, Any]:
    latest = scan.get("latest") or {}
    disp = latest.get("size_dispersion") or {}
    fee = latest.get("fee_slip_stack") or {}
    pools = latest.get("pools") or {}
    return {
        "lane": scan.get("lane"),
        "kill": scan.get("kill"),
        "kill_reason": scan.get("kill_reason"),
        "status": scan.get("status"),
        "snaps": scan.get("snaps"),
        "snaps_ok": scan.get("snaps_ok"),
        "avg_mid": disp.get("avg_mid"),
        "dispersion_bps": disp.get("dispersion_bps"),
        "fee_bps": fee.get("fee_bps"),
        "fee_bps_label": fee.get("fee_bps_label"),
        "slippage_bps": fee.get("slippage_bps"),
        "slippage_bps_label": fee.get("slippage_bps_label"),
        "pool_raydium": (pools.get("raydium") or {}).get("status"),
        "pool_orca": (pools.get("orca") or {}).get("status"),
        "pool_meteora": (pools.get("meteora") or {}).get("status"),
    }


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(
        description=(
            "Jupiter quote-dispersion SCANNER (paper/read-only): size-ladder "
            "/swap/v2/order quote-only mids + fee/slip stack; optional pool RO "
            "mids (deferred when blocked). --live hard-refused. No tips."
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
        help="REFUSED: live swaps / orders are not implemented",
    )
    p.add_argument("--timeout", type=float, default=10.0)
    p.add_argument(
        "--snaps",
        type=int,
        default=1,
        help="Number of full size-ladder passes (thesis path uses >=20 offline)",
    )
    p.add_argument(
        "--size",
        action="append",
        dest="sizes",
        help="Raw lamports size (repeatable); default ladder 0.001..1.0 SOL",
    )
    p.add_argument(
        "--no-pools",
        action="store_true",
        help="Skip Raydium/Orca/Meteora RO probes (Jupiter size-ladder only)",
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
            "Also via env PMM_QUOTE_DISPERSION_ALLOW_FIXTURE=1."
        ),
    )
    p.add_argument("--poll", type=float, default=0.0, help="Poll interval seconds (0 = single)")
    p.add_argument("--max-polls", type=int, default=1)
    p.add_argument("--log", action="store_true", help=f"Append each sample to {DEFAULT_LEDGER}")
    p.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)
    p.add_argument("--prices-only", action="store_true", help="Print compact dispersion view")
    args = p.parse_args(argv)

    if args.live:
        print(json.dumps(_refuse_live(), indent=2, sort_keys=True))
        return 2

    allow_fixture = bool(args.allow_fixture) or _env_allow_fixture()
    poll = float(args.poll)
    max_polls = int(args.max_polls)
    if poll <= 0:
        max_polls = 1
    elif max_polls < 1:
        max_polls = 1

    last_out: dict[str, Any] = {}
    for i in range(max_polls):
        try:
            scan = scan_quote_dispersion(
                sizes=args.sizes or list(DEFAULT_SIZE_LADDER_LAMPORTS),
                timeout=args.timeout,
                allow_fixture=allow_fixture,
                use_fixture=args.fixture,
                probe_pools=not args.no_pools,
                snaps=max(1, int(args.snaps)),
            )
        except DispersionError as e:
            print(json.dumps({
                "ok": False,
                "live": False,
                "mode": "paper",
                "error": str(e),
                "lane": "jupiter_quote_dispersion",
            }, indent=2, sort_keys=True))
            return 1
        if args.log:
            _append_jsonl(Path(args.ledger), scan)

        last_out = {
            "ok": True,
            "mode": "paper",
            "live": False,
            "paper": True,
            "lane": "jupiter_quote_dispersion",
            "allow_fixture": allow_fixture,
            "sample": i + 1,
            "thesis": (
                "Jupiter quote-dispersion T1-plus: size-ladder mids + fee/slip; "
                "optional pool RO (deferred OK); fixture-kill; --live refuse; "
                "no tips; no auto-trade"
            ),
            "scan": scan if not args.prices_only else None,
            "prices": _compact(scan) if args.prices_only else None,
        }
        if args.prices_only:
            print(
                json.dumps(
                    {
                        **{
                            k: last_out[k]
                            for k in ("ok", "mode", "live", "paper", "lane", "sample")
                        },
                        **(last_out.get("prices") or {}),
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
        else:
            print(json.dumps(last_out, indent=2, sort_keys=True))

        if poll > 0 and i + 1 < max_polls:
            time.sleep(poll)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
