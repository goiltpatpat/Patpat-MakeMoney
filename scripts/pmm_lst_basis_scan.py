#!/usr/bin/env python3
"""LST basis SCANNER: Marinade mSOL / jitoSOL fair vs Jupiter LST↔SOL — paper/RO; --live refused.

Protocol fair rates vs Jupiter quote-only LST→SOL. Fee-aware net_basis_bps labeled
ESTIMATE. Fixture-kill default. Never invents rates. No APY tipster, seeds, or live.
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

from venues.basis.bitkub_bnth import opportunity_persisted  # noqa: E402
from venues.basis.lst import (  # noqa: E402
    DEFAULT_LST_AMOUNT,
    LstFeeConfig,
    scan_lst_basis,
)

DEFAULT_LEDGER = ROOT / "runtime" / "lst_basis_ledger.jsonl"


def _refuse_live() -> dict[str, Any]:
    return {
        "ok": False,
        "live": False,
        "error": (
            "REFUSED: --live is not implemented for LST basis. "
            "Paper/read-only scan only — no swaps, no seeds, no tips, no APY tipster."
        ),
        "mode": "paper",
        "execution": "scan_only",
        "asset": "LST",
    }


def _env_allow_fixture() -> bool:
    return os.environ.get("PMM_LST_BASIS_ALLOW_FIXTURE", "").strip().lower() in (
        "1",
        "true",
        "yes",
    ) or os.environ.get("PMM_BASIS_ALLOW_FIXTURE", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def _append_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, sort_keys=True) + "\n")


def _prices_only(scan: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {
        "asset": "LST",
        "kill": scan.get("kill"),
        "kill_reason": scan.get("kill_reason"),
        "opportunity": scan.get("opportunity"),
        "status": scan.get("status"),
    }
    for key, label in (("msol", "mSOL"), ("jitosol", "jitoSOL")):
        lane = scan.get(key) or {}
        legs = lane.get("legs") or {}
        fair = legs.get("fair") or {}
        jup = legs.get("jupiter") or {}
        out[f"{key}_fair"] = fair.get("sol_per_lst")
        out[f"{key}_jupiter"] = jup.get("sol_per_lst")
        out[f"{key}_gross_bps"] = lane.get("gross_basis_bps")
        out[f"{key}_net_bps"] = lane.get("net_basis_bps")
        out[f"{key}_net_label"] = lane.get("net_basis_bps_label") or "ESTIMATE"
        out[f"{key}_direction"] = lane.get("direction")
        out[f"{key}_kill"] = lane.get("kill")
        out[f"{key}_routes"] = (lane.get("dispersion_hint") or {}).get("route_labels")
        out[f"{key}_lst"] = label
    return out


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(
        description=(
            "LST basis SCANNER (paper/read-only): Marinade mSOL fair and/or jitoSOL "
            "stake-pool ratio vs Jupiter LST→SOL quotes. Fee haircuts labeled ESTIMATE. "
            "--live hard-refused. No APY tipster."
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
        help="REFUSED: live LST swaps / orders are not implemented",
    )
    p.add_argument(
        "--lst",
        action="append",
        dest="lsts",
        choices=("mSOL", "jitoSOL"),
        help="LST to scan (repeatable; default both)",
    )
    p.add_argument("--timeout", type=float, default=10.0)
    p.add_argument(
        "--amount",
        default=DEFAULT_LST_AMOUNT,
        help="Raw LST amount for Jupiter quote (9 dp; default 0.1 LST)",
    )
    p.add_argument(
        "--jupiter-fee-bps",
        type=float,
        default=5.0,
        help="Labeled Jupiter fee ESTIMATE (bps; overridden by API feeBps when present)",
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
        default=60.0,
        help="Kill as stale if quote age exceeds this",
    )
    p.add_argument(
        "--rpc-url",
        default=None,
        help="Solana JSON-RPC for jitoSOL stake-pool decode (or PMM_SOL_RPC_URL)",
    )
    p.add_argument(
        "--fixture",
        action="store_true",
        help="Use fixture rates (offline / tests; killed unless --allow-fixture)",
    )
    p.add_argument(
        "--allow-fixture",
        action="store_true",
        help=(
            "Permit fixture rates in opportunity output (OFFLINE TESTS ONLY). "
            "Also via env PMM_LST_BASIS_ALLOW_FIXTURE=1 or PMM_BASIS_ALLOW_FIXTURE=1."
        ),
    )
    p.add_argument("--poll", type=float, default=0.0, help="Poll interval seconds (0 = single)")
    p.add_argument(
        "--persist-sec",
        type=float,
        default=0.0,
        help="With --poll: require |net|>=min-net for this many seconds",
    )
    p.add_argument("--min-persist-sec", type=float, default=None, help="Alias of --persist-sec")
    p.add_argument(
        "--min-persist-samples",
        type=int,
        default=0,
        help="Require N consecutive qualifying samples",
    )
    p.add_argument("--max-polls", type=int, default=1)
    p.add_argument("--log", action="store_true", help=f"Append each sample to {DEFAULT_LEDGER}")
    p.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)
    p.add_argument("--prices-only", action="store_true", help="Print compact prices/bps view")
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
    fees = LstFeeConfig(
        jupiter_fee_bps=args.jupiter_fee_bps,
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
        scan = scan_lst_basis(
            lsts=args.lsts,
            timeout=args.timeout,
            fees=fees,
            allow_fixture=allow_fixture,
            use_fixture=args.fixture,
            max_age_sec=args.max_age_sec,
            amount=args.amount,
            rpc_url=args.rpc_url,
        )
        history.append(scan)
        if args.log:
            _append_jsonl(Path(args.ledger), scan)

        persist_info: Optional[dict[str, Any]] = None
        if min_samples > 0:
            hist_for_persist = []
            for h in history:
                # Prefer mSOL net, else jitoSOL
                lane = h.get("msol") or h.get("jitosol") or {}
                hist_for_persist.append(
                    {
                        "kill": bool(lane.get("kill", True)),
                        "net_basis_bps": lane.get("net_basis_bps"),
                    }
                )
            persist_info = opportunity_persisted(
                hist_for_persist,
                min_samples=min_samples,
                threshold_bps=args.min_net_bps,
            )
        elif persist_sec > 0 and poll <= 0:
            persist_info = {
                "persisted": False,
                "reason": "need_poll",
                "note": "--persist-sec requires --poll to accumulate samples",
            }

        last_out = {
            "ok": True,
            "mode": "paper",
            "live": False,
            "paper": True,
            "asset": "LST",
            "allow_fixture": allow_fixture,
            "sample": i + 1,
            "samples": len(history),
            "thesis": (
                "LST basis: Marinade mSOL fair + jitoSOL stake-pool ratio vs Jupiter "
                "LST→SOL; net_basis_bps ESTIMATE; fixture-kill; --live refuse; "
                "no APY tipster; no auto-trade"
            ),
            "scan": scan if not args.prices_only else None,
            "prices": _prices_only(scan) if args.prices_only else None,
            "persist": persist_info,
        }
        print(json.dumps(last_out if not args.prices_only else {
            **{k: last_out[k] for k in ("ok", "mode", "live", "paper", "asset", "sample")},
            **(last_out.get("prices") or {}),
            "persist": persist_info,
        }, indent=2, sort_keys=True))

        if poll > 0 and i + 1 < max_polls:
            time.sleep(poll)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
