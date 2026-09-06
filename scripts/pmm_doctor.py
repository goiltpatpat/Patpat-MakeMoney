#!/usr/bin/env python3
"""Patpat-MakeMoney desk doctor: validate profiles, paper-first ctl, naming gates."""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FAILS: list[str] = []
PASSES: list[str] = []


def ok(msg: str) -> None:
    PASSES.append(msg)
    print(f"PASS  {msg}")


def bad(msg: str) -> None:
    FAILS.append(msg)
    print(f"FAIL  {msg}")


def load_yaml_profiles(text: str) -> dict[str, dict]:
    """Minimal YAML subset parser for our profiles file (no PyYAML required)."""
    profiles: dict[str, dict] = {}
    current = None
    section = None
    in_profiles = False
    for raw in text.splitlines():
        line = raw.rstrip()
        if line.strip().startswith("#") or not line.strip():
            continue
        if line == "profiles:":
            in_profiles = True
            continue
        if not in_profiles:
            continue
        if line.startswith("runner_mapping:") or (line.startswith("notes:") and not line.startswith(" ")):
            break
        m = re.match(r"^  ([a-zA-Z0-9_]+):\s*$", line)
        if m:
            current = m.group(1)
            profiles[current] = {}
            section = None
            continue
        if current is None:
            continue
        m = re.match(r"^    ([a-zA-Z0-9_]+):\s*$", line)
        if m:
            section = m.group(1)
            profiles[current][section] = {}
            continue
        m = re.match(r"^      ([a-zA-Z0-9_]+):\s*(.+)\s*$", line)
        if m and section:
            key, val = m.group(1), m.group(2).strip().strip('"')
            if val in ("true", "false"):
                profiles[current][section][key] = val == "true"
            else:
                try:
                    profiles[current][section][key] = float(val) if "." in val else int(val)
                except ValueError:
                    profiles[current][section][key] = val
    return profiles


def main() -> int:
    print("=== Patpat-MakeMoney doctor ===")
    cfg = ROOT / "config" / "btc_5m_profiles.yaml"
    ctl = ROOT / "scripts" / "btc5m_ctl.sh"
    runner = ROOT / "scripts" / "test_btc_5m_session_exit_sl.py"
    desk = ROOT / "DESK.md"
    readme = ROOT / "README.md"

    if not cfg.exists():
        bad(f"missing {cfg}")
    else:
        profiles = load_yaml_profiles(cfg.read_text(encoding="utf-8"))
        if "desk" in profiles:
            ok("config has desk profile")
        else:
            bad("config missing desk profile")
        desk_p = profiles.get("desk", {})
        sizing = desk_p.get("sizing", {})
        if sizing.get("stake_usd", 99) <= 5 and sizing.get("daily_max_loss_pct", 99) <= 10:
            ok(f"desk sizing is tight: {sizing}")
        else:
            bad(f"desk sizing not tight enough: {sizing}")

    if not ctl.exists():
        bad("missing btc5m_ctl.sh")
    else:
        text = ctl.read_text(encoding="utf-8")
        if re.search(r'runner_cmd=\([^\)]*"--execute"\)', text, re.S):
            bad("ctl start still hardcodes --execute in runner_cmd array")
        else:
            ok("ctl does not hardcode --execute on every start")
        if "--live|--execute" in text or "--live" in text:
            ok("ctl documents/accepts --live for opt-in execute")
        else:
            bad("ctl missing --live opt-in")
        if 'profile="desk"' in text:
            ok("ctl default profile is desk")
        else:
            bad("ctl default profile is not desk")

    if not runner.exists():
        bad("missing runner")
    else:
        rt = runner.read_text(encoding="utf-8")
        if "'desk'" in rt or '"desk"' in rt:
            ok("runner mentions desk profile")
        else:
            bad("runner missing desk profile wiring")
        if "choices=['conservative', 'aggressive', 'desk']" in rt or "choices=[\"conservative\", \"aggressive\", \"desk\"]" in rt or "desk" in rt and "choices=" in rt:
            # looser check
            if re.search(r"choices=\[([^\]]*'desk'[^\]]*)\]", rt) or re.search(r'choices=\[([^\]]*"desk"[^\]]*)\]', rt):
                ok("runner argparse includes desk")
            else:
                bad("runner argparse choices may omit desk")
        if "'desk':" in rt or '"desk":' in rt:
            ok("runner PROFILES dict includes desk")
        else:
            bad("runner PROFILES dict missing desk")

    for path, label in [(desk, "DESK.md"), (readme, "README.md")]:
        if path.exists() and "Patpat-MakeMoney" in path.read_text(encoding="utf-8"):
            ok(f"{label} branded Patpat-MakeMoney")
        else:
            bad(f"{label} missing Patpat-MakeMoney brand")

    pmm = ROOT / "scripts" / "pmm_ctl.sh"
    if pmm.exists():
        ok("team entry scripts/pmm_ctl.sh present")
    else:
        bad("missing scripts/pmm_ctl.sh")

    hot = ROOT / "scripts" / "btc5m_hot.sh"
    if hot.exists():
        ht = hot.read_text(encoding="utf-8")
        if "desk" in ht and "--live" in ht:
            ok("hot supports desk and --live opt-in")
        else:
            bad("hot missing desk/--live paper-first wiring")
    watch = ROOT / "scripts" / "watch_btc_5m_threshold_and_enter.sh"
    if watch.exists():
        wt = watch.read_text(encoding="utf-8")
        if "LIVE=0" in wt or "PAPER watch" in wt:
            ok("watch is paper-first gated")
        else:
            bad("watch still looks live-hardcoded")

    gates = ROOT / "scripts" / "pmm_gates.py"
    if gates.exists():
        ok("scripts/pmm_gates.py present")
    else:
        bad("missing scripts/pmm_gates.py")

    runner = ROOT / "scripts" / "test_btc_5m_session_exit_sl.py"
    if runner.exists():
        rt = runner.read_text(encoding="utf-8")
        if "'impulse_enabled': False" in rt or '"impulse_enabled": False' in rt or "impulse_enabled': False" in rt:
            ok("runner profiles default impulse_enabled False")
        else:
            # also accept False in desk block
            if "impulse_enabled': False" in rt or "impulse_enabled: False" in rt:
                ok("runner profiles default impulse_enabled False")
            else:
                bad("runner missing impulse_enabled False defaults")
        if "--enable-gates" in rt:
            ok("runner exposes --enable-gates")
        else:
            bad("runner missing --enable-gates")

    print("---")
    print(f"passed={len(PASSES)} failed={len(FAILS)}")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
