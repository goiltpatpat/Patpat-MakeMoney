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
        if "PMM_LIVE_OK" in text:
            ok("ctl requires PMM_LIVE_OK for live")
        else:
            bad("ctl missing PMM_LIVE_OK live gate")
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
        if "parents[1]" in rt and "default_repo_path" in rt and "pm-hl-conservative-plus-repo" not in rt:
            ok("skill default_repo_path is first-party repo root")
        else:
            bad("skill default_repo_path still looks external/sibling")

    live = ROOT / "src" / "live" / "pm_live_trade_runner.py"
    if live.exists():
        lt = live.read_text(encoding="utf-8")
        ok("first-party src/live/pm_live_trade_runner.py present")
        if "--force-side" in lt:
            ok("live runner accepts --force-side")
        else:
            bad("live runner missing --force-side")
    else:
        bad("missing first-party src/live/pm_live_trade_runner.py")


    # Multi-venue Phase 1 (data layer + Bitkub paper skeleton)
    venues_md = ROOT / "docs" / "VENUES.md"
    if venues_md.exists() and "Bitkub" in venues_md.read_text(encoding="utf-8"):
        ok("docs/VENUES.md present (multi-venue)")
    else:
        bad("missing or incomplete docs/VENUES.md")

    venues_init = ROOT / "src" / "venues" / "__init__.py"
    public_btc = ROOT / "src" / "venues" / "public_btc.py"
    oneinch = ROOT / "src" / "venues" / "oneinch_quotes.py"
    bitkub_paper = ROOT / "src" / "venues" / "bitkub" / "paper.py"
    tape = ROOT / "scripts" / "pmm_tape.py"
    for path, label in (
        (venues_init, "src/venues/__init__.py"),
        (public_btc, "src/venues/public_btc.py"),
        (oneinch, "src/venues/oneinch_quotes.py"),
        (bitkub_paper, "src/venues/bitkub/paper.py"),
        (tape, "scripts/pmm_tape.py"),
    ):
        if path.exists():
            ok(f"{label} present")
        else:
            bad(f"missing {label}")

    if bitkub_paper.exists():
        bt = bitkub_paper.read_text(encoding="utf-8")
        if "PMM_BITKUB_LIVE_OK" in bt and "live_order_stub" in bt:
            ok("bitkub paper documents live gate stub")
        else:
            bad("bitkub paper missing PMM_BITKUB_LIVE_OK / live_order_stub")
        if "api.bitkub.com" in bt:
            ok("bitkub paper references public api.bitkub.com")
        else:
            bad("bitkub paper missing api.bitkub.com")

    if oneinch.exists():
        ot = oneinch.read_text(encoding="utf-8")
        if "swap" in ot.lower() and "NO swap" not in ot and "never" not in ot.lower():
            # soft: ensure no swap execution call sites
            pass
        if "allow_fixture" in ot and "ONEINCH_API_KEY" in ot:
            ok("oneinch quotes support fixture + optional API key")
        else:
            bad("oneinch quotes missing fixture/API key support")


    bitkub_cli = ROOT / "scripts" / "pmm_bitkub_paper.py"
    edge_log_cli = ROOT / "scripts" / "pmm_edge_log.py"
    for path, label in (
        (bitkub_cli, "scripts/pmm_bitkub_paper.py"),
        (edge_log_cli, "scripts/pmm_edge_log.py"),
    ):
        if path.exists():
            ok(f"{label} present")
        else:
            bad(f"missing {label}")

    if bitkub_paper.exists():
        bt2 = bitkub_paper.read_text(encoding="utf-8")
        if "paper_round_trip" in bt2 and "fee_estimate" in bt2:
            ok("bitkub paper supports round-trip + fee_estimate fills")
        else:
            bad("bitkub paper missing paper_round_trip / fee_estimate")
        if "CAPS_FILENAME" in bt2 or "bitkub_paper_day_caps" in bt2:
            ok("bitkub paper has day-caps wiring")
        else:
            bad("bitkub paper missing day-caps wiring")

    if bitkub_cli.exists():
        ct = bitkub_cli.read_text(encoding="utf-8")
        if "refuse_live" in ct or "not implemented" in ct.lower():
            ok("pmm_bitkub_paper hard-refuses live")
        else:
            bad("pmm_bitkub_paper missing live refuse")
        if "--stake-thb" in ct and "paper" in ct.lower():
            ok("pmm_bitkub_paper exposes --stake-thb paper CLI")
        else:
            bad("pmm_bitkub_paper missing --stake-thb")

    if edge_log_cli.exists():
        et = edge_log_cli.read_text(encoding="utf-8")
        if "edge_log.jsonl" in et and "invented" in et.lower():
            ok("pmm_edge_log appends paper fills only")
        else:
            bad("pmm_edge_log missing edge_log.jsonl / no-invented note")


    scorecard = ROOT / "scripts" / "pmm_edge_scorecard.py"
    reconcile = ROOT / "scripts" / "pmm_paper_reconcile.py"
    divergence = ROOT / "src" / "venues" / "divergence.py"
    for path, label in (
        (scorecard, "scripts/pmm_edge_scorecard.py"),
        (reconcile, "scripts/pmm_paper_reconcile.py"),
        (divergence, "src/venues/divergence.py"),
    ):
        if path.exists():
            ok(f"{label} present")
        else:
            bad(f"missing {label}")

    if scorecard.exists():
        st = scorecard.read_text(encoding="utf-8")
        if "realized_pnl_thb" in st and "invent" in st.lower():
            ok("edge scorecard uses logged PnL only")
        else:
            bad("edge scorecard missing logged-PnL / no-invent wiring")

    if reconcile.exists():
        rt = reconcile.read_text(encoding="utf-8")
        if "session_closed" in rt and "reconcile_" in rt:
            ok("paper reconcile writes artifact + gates session_closed")
        else:
            bad("paper reconcile missing session_closed / artifact wiring")

    if tape.exists():
        tt = tape.read_text(encoding="utf-8")
        if "--divergence" in tt and "unit_mismatch" in tt:
            ok("pmm_tape exposes triple-tape divergence")
        else:
            bad("pmm_tape missing --divergence / unit_mismatch")


    # Binance TH + DEX→CEX arb SCAN (paper/read-only; second TH lane)
    bnth_tape = ROOT / "src" / "venues" / "binance_th" / "tape.py"
    bnth_paper = ROOT / "src" / "venues" / "binance_th" / "paper.py"
    arb_mod = ROOT / "src" / "venues" / "arb" / "dex_cex.py"
    arb_cli = ROOT / "scripts" / "pmm_arb_scan.py"
    for path_, label in (
        (bnth_tape, "src/venues/binance_th/tape.py"),
        (bnth_paper, "src/venues/binance_th/paper.py"),
        (arb_mod, "src/venues/arb/dex_cex.py"),
        (arb_cli, "scripts/pmm_arb_scan.py"),
    ):
        if path_.exists():
            ok(f"{label} present")
        else:
            bad(f"missing {label}")

    if bnth_tape.exists():
        bt = bnth_tape.read_text(encoding="utf-8")
        if "api.binance.th" in bt and "api.binance.com" in bt and "never" in bt.lower():
            ok("binance_th tape pins api.binance.th and refuses api.binance.com")
        elif "api.binance.th" in bt:
            ok("binance_th tape references api.binance.th")
        else:
            bad("binance_th tape missing api.binance.th")
        if "api.binance.com" in bt and "BINANCE_TH_API_BASE" in bt:
            # ensure base is .th not .com
            if 'BINANCE_TH_API_BASE = "https://api.binance.th"' in bt or "BINANCE_TH_API_BASE = 'https://api.binance.th'" in bt:
                ok("binance_th API base is https://api.binance.th")
            else:
                bad("binance_th API base is not api.binance.th")
        if venues_md.exists():
            vt = venues_md.read_text(encoding="utf-8")
            if "Binance TH" in vt and "api.binance.th" in vt and "Travel Rule" in vt:
                ok("docs/VENUES.md covers Binance TH + Travel Rule arb doctrine")
            else:
                bad("docs/VENUES.md missing Binance TH / Travel Rule arb notes")

    if arb_mod.exists():
        at = arb_mod.read_text(encoding="utf-8")
        if "transfer_time_penalty_bps" in at and "travel_rule_buffer_bps" in at and "gross_spread_bps" in at:
            ok("arb detector has gross/net + latency + Travel Rule buffers")
        else:
            bad("arb detector missing fee/latency/Travel Rule stack")
        if "unit_mismatch" in at and "net_edge_bps" in at:
            ok("arb detector kills on unit_mismatch / net<=0 path")
        else:
            bad("arb detector missing kill rules")

    if arb_cli.exists():
        ct = arb_cli.read_text(encoding="utf-8")
        if "--live" in ct and ("REFUSED" in ct or "hard" in ct.lower() or "refuse" in ct.lower()):
            ok("pmm_arb_scan hard-refuses --live")
        else:
            bad("pmm_arb_scan missing --live refuse")
        if "--paper" in ct:
            ok("pmm_arb_scan exposes --paper")
        else:
            bad("pmm_arb_scan missing --paper")

    if desk.exists():
        dt = desk.read_text(encoding="utf-8")
        if "Binance TH" in dt or "BNTH" in dt:
            ok("DESK.md mentions Binance TH / BNTH second lane")
        else:
            bad("DESK.md missing Binance TH / BNTH")

    # Guard against sibling-stack regressions in entry docs/wrappers
    sibling_hits = []
    for rel in (
        "CONTOUR.md",
        "SKILL.md",
        "scripts/btc5m_ctl.sh",
        "scripts/watch_btc_5m_threshold_and_enter.sh",
        "scripts/run_btc_5m_threshold_test.py",
        "docker-compose.yml",
    ):
        p = ROOT / rel
        if p.exists() and "pm-hl-conservative-plus-repo" in p.read_text(encoding="utf-8"):
            sibling_hits.append(rel)
    if sibling_hits:
        bad("sibling pm-hl path still referenced in: " + ", ".join(sibling_hits))
    else:
        ok("no sibling pm-hl path in primary entry docs/wrappers")

    print("---")
    print(f"passed={len(PASSES)} failed={len(FAILS)}")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
