#!/usr/bin/env python3
"""SOL–THB basis SCANNER: Bitkub+BNTH SOL–THB vs Jupiter×labeled FX — paper/RO; --live hard-refused.

Same-ccy preference (SOL_THB / SOLTHB). USDTTHB from api.binance.th labeled when Jupiter
USDC leg needs FX. Fee-aware net_basis_bps labeled ESTIMATE. Fixture-kill default.
Never invents prices. No seeds, tips, or live orders.
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

from venues.basis.sol_thb import (  # noqa: E402
    DEFAULT_BITKUB_SYMBOL,
    DEFAULT_BNTH_SYMBOL,
    SolThbFeeConfig,
    opportunity_persisted,
    scan_sol_thb_basis,
)

DEFAULT_LEDGER = ROOT / "runtime" / "sol_basis_ledger.jsonl"


def _refuse_live() -> dict[str, Any]:
    return {
        "ok": False,
        "live": False,
        "error": (
            "REFUSED: --live is not implemented for SOL–THB basis. "
            "Paper/read-only scan only — no orders, no seeds, no tips."
        ),
        "mode": "paper",
        "execution": "scan_only",
        "asset": "SOL",
    }


def _env_allow_fixture() -> bool:
    return os.environ.get("PMM_SOL_BASIS_ALLOW_FIXTURE", "").strip().lower() in (
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
    same = scan.get("same_ccy") or {}
    jfx = scan.get("jupiter_fx") or {}
    same_legs = same.get("legs") or {}
    jfx_legs = jfx.get("legs") or {}
    return {
        "asset": "SOL",
        "bitkub_mid": (same_legs.get("bitkub") or {}).get("price"),
        "bnth_mid": (same_legs.get("bnth") or {}).get("price"),
        "same_ccy_gross_bps": same.get("gross_basis_bps"),
        "same_ccy_net_bps": same.get("net_basis_bps"),
        "same_ccy_net_label": same.get("net_basis_bps_label") or "ESTIMATE",
        "same_ccy_direction": same.get("direction"),
        "same_ccy_kill": same.get("kill"),
        "cex_thb_mid": (jfx_legs.get("cex_thb") or {}).get("price"),
        "jupiter_thb_equiv": (jfx_legs.get("jupiter_thb_equiv") or {}).get("price"),
        "fx_usdtthb": (jfx_legs.get("fx") or {}).get("price"),
        "fx_source": (jfx_legs.get("fx") or {}).get("source"),
        "jupiter_fx_gross_bps": jfx.get("gross_basis_bps"),
        "jupiter_fx_net_bps": jfx.get("net_basis_bps"),
        "jupiter_fx_net_label": jfx.get("net_basis_bps_label") or "ESTIMATE",
        "jupiter_fx_direction": jfx.get("direction"),
        "jupiter_fx_kill": jfx.get("kill"),
        "kill": scan.get("kill"),
        "kill_reason": scan.get("kill_reason"),
        "opportunity": scan.get("opportunity"),
        "status": scan.get("status"),
    }


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(
        description=(
            "SOL–THB basis SCANNER (paper/read-only): Bitkub+BNTH SOL–THB mids vs "
            "Jupiter SOL/USDC × labeled USDTTHB. Fee haircuts labeled ESTIMATE. "
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
        help="Labeled Bitkub taker fee ESTIMATE (bps)",
    )
    p.add_argument(
        "--bnth-taker-bps",
        type=float,
        default=10.0,
        help="Labeled BNTH taker fee ESTIMATE (bps)",
    )
    p.add_argument(
        "--jupiter-fee-bps",
        type=float,
        default=5.0,
        help="Labeled Jupiter fee ESTIMATE (bps; overridden by API feeBps when present)",
    )
    p.add_argument(
        "--fx-slip-bps",
        type=float,
        default=2.0,
        help="Labeled FX slip ESTIMATE (bps) on USDTTHB leg",
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
        help="Kill as stale if quote age exceeds this",
    )
    p.add_argument(
        "--no-jupiter",
        action="store_true",
        help="Skip Jupiter×FX lane (same-ccy Bitkub↔BNTH only)",
    )
    p.add_argument(
        "--cex-prefer",
        choices=("bnth", "bitkub", "mid"),
        default="bnth",
        help="Which CEX THB mid to compare vs Jupiter THB-equiv",
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
            "Also via env PMM_SOL_BASIS_ALLOW_FIXTURE=1 or PMM_BASIS_ALLOW_FIXTURE=1."
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
    fees = SolThbFeeConfig(
        bitkub_taker_bps=args.bitkub_taker_bps,
        bnth_taker_bps=args.bnth_taker_bps,
        jupiter_fee_bps=args.jupiter_fee_bps,
        fx_slip_bps=args.fx_slip_bps,
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
        scan = scan_sol_thb_basis(
            bitkub_symbol=args.bitkub_symbol,
            bnth_symbol=args.bnth_symbol,
            timeout=args.timeout,
            fees=fees,
            allow_fixture=allow_fixture,
            use_fixture=args.fixture,
            max_age_sec=args.max_age_sec,
            include_jupiter=not args.no_jupiter,
            cex_prefer=args.cex_prefer,
        )
        history.append(scan)
        if args.log:
            _append_jsonl(Path(args.ledger), scan)

        persist_info: Optional[dict[str, Any]] = None
        if min_samples > 0:
            # Persist on same_ccy net when present, else jupiter_fx net
            hist_for_persist = []
            for h in history:
                same = h.get("same_ccy") or {}
                jfx = h.get("jupiter_fx") or {}
                net = same.get("net_basis_bps")
                kill = bool(same.get("kill", True))
                if net is None:
                    net = jfx.get("net_basis_bps")
                    kill = bool(jfx.get("kill", True))
                hist_for_persist.append({"kill": kill, "net_basis_bps": net})
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
            "asset": "SOL",
            "allow_fixture": allow_fixture,
            "sample": i + 1,
            "samples": len(history),
            "thesis": (
                "SOL–THB basis: same-ccy Bitkub SOL_THB ↔ BNTH SOLTHB + Jupiter SOL/USDC "
                "× labeled BNTH USDTTHB; net_basis_bps ESTIMATE; fixture-kill; --live refuse"
            ),
            "basis": scan,
            "persist": persist_info,
            "prices": _prices_only(scan),
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
