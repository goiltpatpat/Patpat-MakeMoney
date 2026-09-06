#!/usr/bin/env python3
"""Post-stop paper reconcile — write runtime/reconcile_<ts>.json checklist (paper-only).

Blocks session_closed=true unless the reconcile artifact is written.
No live Bitkub/PM execute. No invented PnL.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RUNTIME = ROOT / "runtime"
DEFAULT_LOG = DEFAULT_RUNTIME / "edge_log.jsonl"
DEFAULT_STATE = DEFAULT_RUNTIME / "bitkub_paper_day_state.json"
DEFAULT_CAPS = DEFAULT_RUNTIME / "bitkub_paper_day_caps.json"
EDGE_TAIL_N = 10


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_stamp() -> str:
    return _utc_now().strftime("%Y%m%dT%H%M%SZ")


def _utc_now_iso() -> str:
    return _utc_now().strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_json_optional(path: Path) -> Optional[dict[str, Any]]:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, OSError):
        return None
    return data if isinstance(data, dict) else None


def _tail_edge_log(log_path: Path, n: int = EDGE_TAIL_N) -> list[dict[str, Any]]:
    if not log_path.exists():
        return []
    lines = [ln.strip() for ln in log_path.read_text(encoding="utf-8-sig").splitlines() if ln.strip()]
    tail = lines[-n:] if n > 0 else lines
    out: list[dict[str, Any]] = []
    for ln in tail:
        try:
            obj = json.loads(ln)
        except json.JSONDecodeError:
            out.append({"raw": ln, "parse_error": True})
            continue
        if isinstance(obj, dict) and obj.get("live") is True:
            raise ValueError("refusing live=true edge_log record — reconcile is paper-only")
        if isinstance(obj, dict):
            out.append(obj)
    return out


def build_reconcile_payload(
    *,
    runtime_dir: Path,
    log_path: Path,
    state_path: Path,
    caps_path: Path,
    edge_tail_n: int = EDGE_TAIL_N,
    mark_session_closed: bool = False,
) -> dict[str, Any]:
    """Build checklist payload. session_closed stays false until artifact is written by write_reconcile."""
    day_state = _load_json_optional(state_path)
    day_caps = _load_json_optional(caps_path)
    edge_tails = _tail_edge_log(log_path, n=edge_tail_n)

    # Bitkub paper adapter has no resting orders / open positions by design
    open_paper_positions: list[dict[str, Any]] = []
    positions_note = (
        "Bitkub paper has no resting orders — positions are flat after each open+close "
        "round-trip; no open paper book to reconcile"
    )

    checklist = {
        "day_state": {
            "path": str(state_path),
            "present": day_state is not None,
            "value": day_state,
        },
        "edge_log_tails": {
            "path": str(log_path),
            "present": log_path.exists(),
            "tail_n": edge_tail_n,
            "records": edge_tails,
        },
        "open_paper_positions": {
            "count": len(open_paper_positions),
            "positions": open_paper_positions,
            "flat": True,
            "note": positions_note,
        },
        "manual_steps_future_live": [
            "Confirm PMM_BITKUB_LIVE_OK + API creds only after paper expectancy falsified",
            "Cancel any resting live orders on venue UI/API (paper path has none)",
            "Reconcile live fills vs edge_log — never invent PnL",
            "Reset or archive day_state before next live session",
            "Run pmm_live_preflight.py and keep process-stop ready (ctl stop)",
        ],
    }

    return {
        "ok": True,
        "mode": "paper",
        "live": False,
        "generated_at": _utc_now_iso(),
        "role": "Thesis",
        "artifact": "paper_reconcile",
        "session_closed": False if not mark_session_closed else True,
        "note": "Post-stop paper reconcile checklist — no live execute; no invented PnL",
        "checklist": checklist,
        "day_caps": day_caps,
        "runtime_dir": str(runtime_dir),
    }


def write_reconcile(
    *,
    runtime_dir: Path = DEFAULT_RUNTIME,
    log_path: Optional[Path] = None,
    state_path: Optional[Path] = None,
    caps_path: Optional[Path] = None,
    edge_tail_n: int = EDGE_TAIL_N,
    session_closed: bool = True,
    ts: Optional[str] = None,
) -> dict[str, Any]:
    """
    Write runtime/reconcile_<ts>.json.

    session_closed=True is only set on the written artifact (and returned payload)
    after the file is successfully written. Callers cannot claim session_closed
    without an on-disk artifact.
    """
    runtime_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_path or (runtime_dir / "edge_log.jsonl")
    state_path = state_path or (runtime_dir / "bitkub_paper_day_state.json")
    caps_path = caps_path or (runtime_dir / "bitkub_paper_day_caps.json")
    stamp = ts or _utc_stamp()
    out_path = runtime_dir / f"reconcile_{stamp}.json"

    # Build with session_closed=false first; flip only after write succeeds
    payload = build_reconcile_payload(
        runtime_dir=runtime_dir,
        log_path=log_path,
        state_path=state_path,
        caps_path=caps_path,
        edge_tail_n=edge_tail_n,
        mark_session_closed=False,
    )
    if not session_closed:
        # Explicit dry / preview: write artifact but leave session_closed false
        payload["session_closed"] = False
        payload["session_closed_blocked_reason"] = None
        out_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        payload["reconcile_path"] = str(out_path)
        return payload

    # Want session_closed=true: write then set flag on disk
    payload["session_closed"] = False
    payload["session_closed_blocked_reason"] = (
        "session_closed blocked until reconcile artifact written"
    )
    # Write intermediate then rewrite with closed=true atomically enough for desk use
    out_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if not out_path.exists() or out_path.stat().st_size <= 0:
        raise RuntimeError("reconcile artifact write failed — refusing session_closed=true")
    payload["session_closed"] = True
    payload["session_closed_blocked_reason"] = None
    payload["reconcile_path"] = str(out_path)
    out_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return payload


def claim_session_closed_without_artifact() -> dict[str, Any]:
    """Hard block helper for tests / callers that try to close without writing."""
    return {
        "ok": False,
        "session_closed": False,
        "error": "session_closed=true blocked unless reconcile artifact written",
        "live": False,
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Write post-stop paper reconcile checklist under runtime/ (paper-only)."
    )
    p.add_argument("--runtime-dir", type=Path, default=DEFAULT_RUNTIME)
    p.add_argument("--log", type=Path, default=None, help="edge_log.jsonl (default: runtime/)")
    p.add_argument("--state", type=Path, default=None)
    p.add_argument("--caps", type=Path, default=None)
    p.add_argument("--tail", type=int, default=EDGE_TAIL_N, help="edge_log tail lines")
    p.add_argument(
        "--no-close",
        action="store_true",
        help="Write artifact but leave session_closed=false",
    )
    p.add_argument(
        "--preview",
        action="store_true",
        help="Print payload without writing (session_closed stays false)",
    )
    args = p.parse_args(argv)

    if args.preview:
        payload = build_reconcile_payload(
            runtime_dir=args.runtime_dir,
            log_path=args.log or (args.runtime_dir / "edge_log.jsonl"),
            state_path=args.state or (args.runtime_dir / "bitkub_paper_day_state.json"),
            caps_path=args.caps or (args.runtime_dir / "bitkub_paper_day_caps.json"),
            edge_tail_n=args.tail,
            mark_session_closed=False,
        )
        payload["session_closed"] = False
        payload["session_closed_blocked_reason"] = (
            "preview only — artifact not written; session_closed blocked"
        )
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0

    try:
        out = write_reconcile(
            runtime_dir=args.runtime_dir,
            log_path=args.log,
            state_path=args.state,
            caps_path=args.caps,
            edge_tail_n=args.tail,
            session_closed=not args.no_close,
        )
    except ValueError as e:
        print(json.dumps({"ok": False, "error": str(e), "session_closed": False}, indent=2))
        return 1
    except OSError as e:
        print(json.dumps({"ok": False, "error": str(e), "session_closed": False}, indent=2))
        return 1

    print(json.dumps(out, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
