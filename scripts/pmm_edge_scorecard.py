#!/usr/bin/env python3
"""Edge scorecard — Thesis cage falsify brief from runtime/edge_log.jsonl (paper-only).

Reads logged fill fields ONLY. Never invents prices or PnL.
Emits Ledger JSON for expectancy / hit-rate / day-cap stop flags.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LOG = ROOT / "runtime" / "edge_log.jsonl"
DEFAULT_STATE = ROOT / "runtime" / "bitkub_paper_day_state.json"
DEFAULT_CAPS = ROOT / "runtime" / "bitkub_paper_day_caps.json"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_edge_records(log_path: Path) -> list[dict[str, Any]]:
    """Load JSONL edge records. Skips blank lines; raises on malformed JSON."""
    if not log_path.exists():
        return []
    records: list[dict[str, Any]] = []
    for i, line in enumerate(log_path.read_text(encoding="utf-8-sig").splitlines(), start=1):
        raw = line.strip()
        if not raw:
            continue
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError as e:
            raise ValueError(f"malformed JSONL at {log_path}:{i}: {e}") from e
        if not isinstance(obj, dict):
            raise ValueError(f"edge_log line {i} must be a JSON object")
        if obj.get("live") is True:
            raise ValueError(f"refusing live=true record at line {i} — scorecard is paper-only")
        records.append(obj)
    return records


def _mean(values: list[float]) -> Optional[float]:
    if not values:
        return None
    return round(sum(values) / len(values), 8)


def compute_scorecard(
    records: list[dict[str, Any]],
    *,
    day_state: Optional[dict[str, Any]] = None,
    day_caps: Optional[dict[str, Any]] = None,
    skip_events: Optional[list[dict[str, Any]]] = None,
) -> dict[str, Any]:
    """
    Build Ledger scorecard from logged fields only.

    - n_fills: count of fill records
    - n_round_trips: distinct round_trip_id among records that have one
    - mean_realized_pnl_thb: mean of non-null realized_pnl_thb (close legs); None if none logged
    - fill_rate: only if skip_events / skip counts present; else null + note
    - day_cap_stop: from day_state when present
    """
    n_fills = len(records)
    rt_ids = sorted(
        {
            str(r["round_trip_id"])
            for r in records
            if r.get("round_trip_id") not in (None, "")
        }
    )
    # PnL ONLY from logged realized_pnl_thb — never recompute from px/size
    pnl_vals: list[float] = []
    for r in records:
        v = r.get("realized_pnl_thb")
        if v is None:
            continue
        try:
            pnl_vals.append(float(v))
        except (TypeError, ValueError):
            raise ValueError(f"non-numeric realized_pnl_thb in log: {v!r}") from None

    mean_pnl = _mean(pnl_vals)
    hit = sum(1 for v in pnl_vals if v > 0)
    miss = sum(1 for v in pnl_vals if v < 0)
    flat = sum(1 for v in pnl_vals if v == 0.0)

    fill_rate: Optional[float] = None
    fill_rate_note = "fill_rate omitted — no skip data present (refuse inventing)"
    skips = list(skip_events or [])
    # Also accept skip markers inside edge_log records
    log_skips = [r for r in records if r.get("event") == "skip" or r.get("skipped") is True]
    if log_skips:
        skips.extend(log_skips)
    n_skips = len(skips)
    if n_skips > 0 or any(r.get("skip_count") is not None for r in records):
        # Prefer explicit skip_count sum if present
        explicit = [r.get("skip_count") for r in records if r.get("skip_count") is not None]
        if explicit:
            try:
                n_skips = int(sum(float(x) for x in explicit))
            except (TypeError, ValueError):
                pass
        attempts = n_fills + n_skips
        if attempts > 0:
            fill_rate = round(n_fills / attempts, 6)
            fill_rate_note = f"fill_rate = n_fills/({n_fills}+{n_skips} skips) from logged skip data"
        else:
            fill_rate_note = "skip data present but attempts=0"

    day_cap_stop: dict[str, Any] = {
        "present": day_state is not None,
        "stopped": None,
        "stop_reason": None,
        "state": day_state,
        "caps": day_caps,
    }
    if isinstance(day_state, dict):
        day_cap_stop["stopped"] = bool(day_state.get("stopped"))
        day_cap_stop["stop_reason"] = day_state.get("stop_reason")

    return {
        "ok": True,
        "mode": "paper",
        "live": False,
        "generated_at": _utc_now_iso(),
        "role": "Thesis",
        "artifact": "edge_scorecard",
        "note": (
            "Falsifiable paper scorecard from edge_log fields only — "
            "no invented PnL; mean_realized_pnl_thb uses logged realized_pnl_thb values"
        ),
        "n_fills": n_fills,
        "n_round_trips": len(rt_ids),
        "round_trip_ids": rt_ids,
        "n_realized_pnl_samples": len(pnl_vals),
        "mean_realized_pnl_thb": mean_pnl,
        "hit_count": hit if pnl_vals else None,
        "miss_count": miss if pnl_vals else None,
        "flat_count": flat if pnl_vals else None,
        "hit_rate": round(hit / len(pnl_vals), 6) if pnl_vals else None,
        "fill_rate": fill_rate,
        "fill_rate_note": fill_rate_note,
        "n_skips": n_skips if (fill_rate is not None or n_skips > 0) else None,
        "day_cap_stop": day_cap_stop,
        "pnl_basis": "logged realized_pnl_thb only — scorecard does not recompute from px/size",
    }


def _load_json_optional(path: Path) -> Optional[dict[str, Any]]:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, OSError):
        return None
    return data if isinstance(data, dict) else None


def build_scorecard_from_paths(
    *,
    log_path: Path = DEFAULT_LOG,
    state_path: Path = DEFAULT_STATE,
    caps_path: Path = DEFAULT_CAPS,
    skip_path: Optional[Path] = None,
) -> dict[str, Any]:
    records = load_edge_records(log_path)
    day_state = _load_json_optional(state_path)
    day_caps = _load_json_optional(caps_path)
    skip_events: Optional[list[dict[str, Any]]] = None
    if skip_path is not None and skip_path.exists():
        raw = json.loads(skip_path.read_text(encoding="utf-8-sig"))
        if isinstance(raw, list):
            skip_events = [x for x in raw if isinstance(x, dict)]
        elif isinstance(raw, dict) and isinstance(raw.get("skips"), list):
            skip_events = [x for x in raw["skips"] if isinstance(x, dict)]
    out = compute_scorecard(
        records,
        day_state=day_state,
        day_caps=day_caps,
        skip_events=skip_events,
    )
    out["inputs"] = {
        "edge_log": str(log_path),
        "day_state": str(state_path) if day_state is not None else None,
        "day_caps": str(caps_path) if day_caps is not None else None,
        "skip_path": str(skip_path) if skip_path else None,
    }
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Thesis edge scorecard from runtime/edge_log.jsonl (paper-only; no invented PnL)."
    )
    p.add_argument("--log", type=Path, default=DEFAULT_LOG, help="edge_log.jsonl path")
    p.add_argument("--state", type=Path, default=DEFAULT_STATE, help="day state JSON (optional)")
    p.add_argument("--caps", type=Path, default=DEFAULT_CAPS, help="day caps JSON (optional)")
    p.add_argument(
        "--skips",
        type=Path,
        default=None,
        help="Optional skip events JSON (list or {skips:[...]}) for fill-rate",
    )
    args = p.parse_args(argv)
    try:
        out = build_scorecard_from_paths(
            log_path=args.log,
            state_path=args.state,
            caps_path=args.caps,
            skip_path=args.skips,
        )
    except ValueError as e:
        print(json.dumps({"ok": False, "error": str(e), "live": False}, indent=2))
        return 1
    print(json.dumps(out, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
