#!/usr/bin/env python3
"""Live readiness preflight for Patpat-MakeMoney (does not place orders)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import pmm_live_guard  # noqa: E402

FAILS: list[str] = []
PASSES: list[str] = []


def ok(m: str) -> None:
    PASSES.append(m)
    print(f"PASS  {m}")


def bad(m: str) -> None:
    FAILS.append(m)
    print(f"FAIL  {m}")


def main() -> int:
    print("=== Patpat-MakeMoney live preflight ===")
    print("NOTE: this does not enable live and does not place orders.")

    live = ROOT / "src" / "live" / "pm_live_trade_runner.py"
    if live.exists() and "--force-side" in live.read_text(encoding="utf-8"):
        ok("first-party live runner + force-side")
    else:
        bad("live runner/force-side missing")

    vpy = ROOT / ".venv" / "bin" / "python"
    if vpy.exists():
        ok(".venv/bin/python present")
    else:
        bad("missing .venv/bin/python — create with requirements-exec.txt")

    env_path = Path(os.environ.get("BTC5M_ENV_FILE") or (ROOT / ".env"))
    if env_path.exists():
        ok(f"env file present: {env_path}")
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            if k and v and k not in os.environ:
                os.environ[k] = v.strip().strip('"').strip("'")
    else:
        bad(f"missing env file {env_path} (copy .env.example)")

    cred_ok, missing = pmm_live_guard.env_has_live_creds()
    if cred_ok:
        ok("required PM_* creds present in environment (values not shown)")
    else:
        bad("missing creds: " + ", ".join(missing))

    if str(os.environ.get("PMM_LIVE_OK", "")).strip() == "1":
        ok("PMM_LIVE_OK=1 set (desk gate acknowledged)")
    else:
        bad("PMM_LIVE_OK not set — required for ctl --live / skill --execute")

    try:
        import py_clob_client  # noqa: F401
        ok("py_clob_client importable in this interpreter")
    except Exception as e:
        bad(f"py_clob_client import failed in this interpreter: {e}")

    print("---")
    print(f"passed={len(PASSES)} failed={len(FAILS)}")
    if FAILS:
        print("LIVE_READY=no")
        return 1
    print("LIVE_READY=yes — still requires explicit human start with --live/--execute")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
