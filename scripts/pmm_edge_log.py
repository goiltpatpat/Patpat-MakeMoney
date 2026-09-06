#!/usr/bin/env python3
"""Append paper fills to runtime/edge_log.jsonl for later expectancy falsify (Thesis cage).

No invented PnL — only records fills / round-trips supplied by paper adapters.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LOG = ROOT / "runtime" / "edge_log.jsonl"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _extract_fills(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Normalize open/close, batch fills[], or single fill payloads into fill records."""
    fills: list[dict[str, Any]] = []
    if "open" in payload and "close" in payload:
        for leg in ("open", "close"):
            f = payload.get(leg)
            if isinstance(f, dict):
                fills.append(dict(f))
        return fills
    if "fills" in payload and isinstance(payload["fills"], list):
        for f in payload["fills"]:
            if isinstance(f, dict):
                fills.append(dict(f))
        return fills
    if "fill" in payload and isinstance(payload["fill"], dict):
        fills.append(dict(payload["fill"]))
        return fills
    # Already a fill-shaped object
    if payload.get("side") and (payload.get("px") is not None or payload.get("fill_price") is not None):
        fills.append(dict(payload))
    return fills


def append_edge_log(
    payload: dict[str, Any],
    *,
    log_path: Path = DEFAULT_LOG,
    source: str = "paper",
) -> dict[str, Any]:
    """Append one JSONL record per paper fill. Returns summary."""
    if payload.get("live") is True:
        raise ValueError("refusing to log live fills — edge_log is paper-only")
    fills = _extract_fills(payload)
    if not fills:
        raise ValueError("no paper fills found in payload")

    log_path.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    records = []
    with log_path.open("a", encoding="utf-8") as fh:
        for f in fills:
            if f.get("live") is True:
                raise ValueError("refusing fill with live=true")
            rec = {
                "logged_at": _utc_now_iso(),
                "source": source,
                "venue": f.get("venue") or payload.get("venue") or "unknown",
                "mode": "paper",
                "symbol": f.get("symbol") or payload.get("symbol"),
                "side": f.get("side"),
                "size": f.get("size"),
                "px": f.get("px", f.get("fill_price")),
                "fee_estimate": f.get("fee_estimate"),
                "ts": f.get("ts"),
                "leg": f.get("leg"),
                "round_trip_id": f.get("round_trip_id") or payload.get("round_trip_id"),
                "realized_pnl_thb": payload.get("realized_pnl_thb") if f.get("leg") == "close" else None,
                "pnl_basis": payload.get("pnl_basis") if f.get("leg") == "close" else None,
                "note": "paper fill only — no invented PnL beyond fill-derived fields",
            }
            fh.write(json.dumps(rec, sort_keys=True) + "\n")
            records.append(rec)
            written += 1
    return {"ok": True, "written": written, "log_path": str(log_path), "records": records}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Append paper fills to runtime/edge_log.jsonl")
    p.add_argument(
        "--from-json",
        help="Path to paper round-trip / fill JSON (from pmm_bitkub_paper.py)",
    )
    p.add_argument(
        "--stdin",
        action="store_true",
        help="Read JSON payload from stdin",
    )
    p.add_argument(
        "--log",
        type=Path,
        default=DEFAULT_LOG,
        help="edge_log.jsonl path (default: runtime/edge_log.jsonl)",
    )
    p.add_argument("--source", default="paper", help="source tag for Thesis cage")
    args = p.parse_args(argv)

    if args.stdin:
        raw = sys.stdin.read()
    elif args.from_json:
        raw = Path(args.from_json).read_text(encoding="utf-8-sig")
    else:
        p.error("provide --from-json PATH or --stdin")

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as e:
        print(json.dumps({"ok": False, "error": f"invalid JSON: {e}"}))
        return 1
    if not isinstance(payload, dict):
        print(json.dumps({"ok": False, "error": "payload must be a JSON object"}))
        return 1

    try:
        out = append_edge_log(payload, log_path=args.log, source=args.source)
    except ValueError as e:
        print(json.dumps({"ok": False, "error": str(e)}))
        return 1

    # Compact stdout for ctl piping (omit full records echo by default summary)
    print(json.dumps({"ok": out["ok"], "written": out["written"], "log_path": out["log_path"]}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
