"""Patpat-MakeMoney live/paper isolation helpers."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Align with config/btc_5m_profiles.yaml shared_rules.execution_safety
DEFAULT_MAX_SPREAD = "0.03"
DEFAULT_MIN_TOP_ASK_NOTIONAL_USD = "30"
LIVE_OK_ENV = "PMM_LIVE_OK"


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def runtime_dir(root: Path | None = None) -> Path:
    d = (root or repo_root()) / "runtime"
    d.mkdir(parents=True, exist_ok=True)
    return d


def utc_day() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def day_state_path(root: Path | None = None) -> Path:
    return runtime_dir(root) / f"desk_day_{utc_day()}.json"


def load_day_state(root: Path | None = None) -> dict[str, Any]:
    p = day_state_path(root)
    if not p.exists():
        return {"day": utc_day(), "trades": 0, "realized_pnl_usdc": 0.0}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if data.get("day") != utc_day():
            return {"day": utc_day(), "trades": 0, "realized_pnl_usdc": 0.0}
        return data
    except Exception:
        return {"day": utc_day(), "trades": 0, "realized_pnl_usdc": 0.0}


def save_day_state(state: dict[str, Any], root: Path | None = None) -> None:
    p = day_state_path(root)
    p.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def record_live_trade(realized_pnl_usdc: float | None = None, root: Path | None = None) -> dict[str, Any]:
    st = load_day_state(root)
    st["trades"] = int(st.get("trades") or 0) + 1
    if realized_pnl_usdc is not None:
        st["realized_pnl_usdc"] = float(st.get("realized_pnl_usdc") or 0.0) + float(realized_pnl_usdc)
    save_day_state(st, root)
    return st


def can_open_live(max_trades_per_day: int, daily_max_loss_usdc: float | None = None, root: Path | None = None) -> tuple[bool, str, dict[str, Any]]:
    st = load_day_state(root)
    trades = int(st.get("trades") or 0)
    if trades >= int(max_trades_per_day):
        return False, "skip_max_trades_per_day", st
    pnl = float(st.get("realized_pnl_usdc") or 0.0)
    if daily_max_loss_usdc is not None and pnl <= -abs(float(daily_max_loss_usdc)):
        return False, "skip_daily_max_loss", st
    return True, "ok", st


def require_live_ok(execute: bool) -> None:
    """Hard gate: --execute requires PMM_LIVE_OK=1 in the environment."""
    if not execute:
        return
    if str(os.environ.get(LIVE_OK_ENV, "")).strip() != "1":
        raise SystemExit(
            f"refusing --execute: set {LIVE_OK_ENV}=1 after Ledger/human desk gate "
            "(paper is default; this prevents one-flag live footguns)."
        )


def open_exec_env(base: dict[str, str] | None = None) -> dict[str, str]:
    """Desk-tight CLOB open guards (do not fail-open to permissive defaults)."""
    env = dict(base or os.environ)
    # Always enforce desk-tight values for skill-driven opens (override loose shells).
    env["PM_MAX_SPREAD"] = os.environ.get("PMM_MAX_SPREAD", DEFAULT_MAX_SPREAD)
    env["PM_MIN_TOP_ASK_NOTIONAL_USD"] = os.environ.get(
        "PMM_MIN_TOP_ASK_NOTIONAL_USD", DEFAULT_MIN_TOP_ASK_NOTIONAL_USD
    )
    env.setdefault("PM_ORDER_TYPE", "FAK")
    return env


def env_has_live_creds() -> tuple[bool, list[str]]:
    missing = []
    for k in ("PM_PRIVATE_KEY", "PM_API_KEY", "PM_API_SECRET", "PM_API_PASSPHRASE"):
        if not str(os.environ.get(k) or "").strip():
            missing.append(k)
    # funder optional but recommended
    if not (os.environ.get("PM_FUNDER") or os.environ.get("PM_ADDRESS")):
        missing.append("PM_FUNDER|PM_ADDRESS")
    # treat funder as warning-only: required list without it for hard fail
    hard = [m for m in missing if not m.startswith("PM_FUNDER")]
    return len(hard) == 0, missing
