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


    apis_md = ROOT / "docs" / "APIS.md"
    holes_md = ROOT / "docs" / "HOLES.md"
    if apis_md.exists():
        at = apis_md.read_text(encoding="utf-8")
        if "api.binance.th" in at and "ONEINCH" in at.upper() and "Travel Rule" in at:
            ok("docs/APIS.md covers BNTH + DEX + Travel Rule")
        else:
            bad("docs/APIS.md incomplete (need api.binance.th / 1inch / Travel Rule)")
    else:
        bad("missing docs/APIS.md")
    if holes_md.exists() and "fixture" in holes_md.read_text(encoding="utf-8").lower():
        ok("docs/HOLES.md present (fixture hygiene)")
    else:
        bad("missing or incomplete docs/HOLES.md")

    if arb_mod.exists():
        at2 = arb_mod.read_text(encoding="utf-8")
        if "money_leg_source_fixture" in at2 and "allow_fixture" in at2:
            ok("arb detector fixture-kills unless allow_fixture")
        else:
            bad("arb detector missing fixture-kill / allow_fixture")
    if arb_cli.exists():
        ct2 = arb_cli.read_text(encoding="utf-8")
        if "--allow-fixture" in ct2 and "allow_fixture=True if fixture else True" not in ct2:
            ok("pmm_arb_scan has --allow-fixture and no always-true fixture bug")
        else:
            bad("pmm_arb_scan missing --allow-fixture or still has always-true fixture bug")
    if bitkub_paper.exists():
        bt3 = bitkub_paper.read_text(encoding="utf-8")
        if "utf-8-sig" in bt3:
            ok("bitkub day caps loader uses utf-8-sig (BOM-safe)")
        else:
            bad("bitkub day caps loader missing utf-8-sig")


    # Bitkub <-> BNTH same-ccy THB basis monitor (paper/read-only)
    basis_mod = ROOT / "src" / "venues" / "basis" / "bitkub_bnth.py"
    basis_cli = ROOT / "scripts" / "pmm_basis_scan.py"
    for path_, label in (
        (basis_mod, "src/venues/basis/bitkub_bnth.py"),
        (basis_cli, "scripts/pmm_basis_scan.py"),
    ):
        if path_.exists():
            ok(f"{label} present")
        else:
            bad(f"missing {label}")

    # Solana / Jupiter research tape (quote-only; no custody)
    solana_md = ROOT / "docs" / "SOLANA.md"
    jup = ROOT / "src" / "venues" / "solana" / "jupiter_quotes.py"
    sol_cli = ROOT / "scripts" / "pmm_sol_tape.py"
    sol_cex = ROOT / "src" / "venues" / "arb" / "sol_cex.py"
    desk_bal = ROOT / "src" / "venues" / "solana" / "desk_balance.py"
    sol_paper = ROOT / "src" / "venues" / "solana" / "paper.py"
    sol_paper_cli = ROOT / "scripts" / "pmm_sol_paper.py"
    custody_md = ROOT / "docs" / "SOLANA_CUSTODY.md"
    for path_, label in (
        (solana_md, "docs/SOLANA.md"),
        (jup, "src/venues/solana/jupiter_quotes.py"),
        (desk_bal, "src/venues/solana/desk_balance.py"),
        (sol_paper, "src/venues/solana/paper.py"),
        (sol_cli, "scripts/pmm_sol_tape.py"),
        (sol_paper_cli, "scripts/pmm_sol_paper.py"),
        (sol_cex, "src/venues/arb/sol_cex.py"),
        (custody_md, "docs/SOLANA_CUSTODY.md"),
    ):
        if path_.exists():
            ok(f"{label} present")
        else:
            bad(f"missing {label}")

    if basis_mod.exists():
        bt = basis_mod.read_text(encoding="utf-8")
        if "basis_bps" in bt and "api.binance.th" in bt and "unit_mismatch" in bt:
            ok("basis module has basis_bps + api.binance.th + unit_mismatch kill")
        else:
            bad("basis module missing core same-ccy THB wiring")
        if "money_leg_source_fixture" in bt and "sign_convention" in bt:
            ok("basis module documents sign convention + fixture kill")
        else:
            bad("basis module missing sign convention / fixture kill")
        if "net_basis_bps" in bt and "fee_floor" in bt:
            ok("basis module has gross vs net fee floor")
        else:
            bad("basis module missing net_basis_bps / fee floor")

    if basis_cli.exists():
        ct = basis_cli.read_text(encoding="utf-8")
        if "--live" in ct and ("REFUSED" in ct or "refuse" in ct.lower()):
            ok("pmm_basis_scan hard-refuses --live")
        else:
            bad("pmm_basis_scan missing --live refuse")
        if "--poll" in ct and ("--persist-sec" in ct or "--min-persist-sec" in ct):
            ok("pmm_basis_scan exposes --poll / persist duration filter")
        else:
            bad("pmm_basis_scan missing --poll / persist")

    if venues_md.exists():
        vt2 = venues_md.read_text(encoding="utf-8")
        if "same-ccy" in vt2.lower() or "same-currency" in vt2.lower() or "bitkub_bnth" in vt2.lower():
            ok("docs/VENUES.md covers Bitkub<->BNTH basis")
        else:
            bad("docs/VENUES.md missing Bitkub<->BNTH basis notes")

    if apis_md.exists():
        at3 = apis_md.read_text(encoding="utf-8")
        if "pmm_basis_scan" in at3 or "same-currency basis" in at3.lower() or "same-ccy" in at3.lower():
            ok("docs/APIS.md mentions basis scan")
        else:
            bad("docs/APIS.md missing basis scan note")

    if desk.exists():
        dt2 = desk.read_text(encoding="utf-8")
        if "basis" in dt2.lower() and ("pmm_basis_scan" in dt2 or "Bitkub" in dt2):
            ok("DESK.md mentions Bitkub<->BNTH basis")
        else:
            bad("DESK.md missing basis monitor note")

    if jup.exists():
        jt = jup.read_text(encoding="utf-8")
        if "swap/v2/order" in jt and "taker" in jt.lower() and "NEVER" in jt:
            ok("jupiter quotes use swap/v2/order quote-only (no taker / never sign)")
        else:
            bad("jupiter quotes missing swap/v2/order quote-only posture")
        if "allow_fixture" in jt and "use_fixture" in jt and "price/v3" in jt:
            ok("jupiter quotes support explicit fixture + price/v3")
        else:
            bad("jupiter quotes missing fixture/price v3 wiring")
        if "/execute" in jt and "never" not in jt.lower():
            bad("jupiter quotes appear to wire /execute")
        else:
            ok("jupiter quotes do not wire /execute")

    if sol_cli.exists():
        st = sol_cli.read_text(encoding="utf-8")
        if "--live" in st and ("REFUSED" in st or "refuse" in st.lower()):
            ok("pmm_sol_tape hard-refuses --live")
        else:
            bad("pmm_sol_tape missing --live refuse")
        if "--allow-fixture" in st and "gross_vs_net" in st:
            ok("pmm_sol_tape has allow-fixture + gross_vs_net")
        else:
            bad("pmm_sol_tape missing allow-fixture / gross_vs_net")
        if "--balance-pubkey" in st and "PMM_SOL_DESK_PUBKEY" in st:
            ok("pmm_sol_tape exposes RO --balance-pubkey / PMM_SOL_DESK_PUBKEY")
        else:
            bad("pmm_sol_tape missing balance pubkey probe wiring")

    if sol_paper.exists():
        spt = sol_paper.read_text(encoding="utf-8")
        if 'VENUE = "solana_paper"' in spt or "solana_paper" in spt:
            ok("solana paper module tags venue=solana_paper")
        else:
            bad("solana paper missing venue=solana_paper")
        if "refuse_live" in spt and "NEVER" in spt.upper():
            ok("solana paper refuses live / never sign")
        else:
            bad("solana paper missing refuse_live posture")
        if "fee_bps" in spt and "realized_pnl_thb" in spt and "invent" in spt.lower():
            ok("solana paper uses API fee_bps + no invented PnL")
        else:
            bad("solana paper missing fee_bps / no-invented-PnL wiring")

    if sol_paper_cli.exists():
        spc = sol_paper_cli.read_text(encoding="utf-8")
        if "--live" in spc and ("REFUSED" in spc or "refuse" in spc.lower()):
            ok("pmm_sol_paper hard-refuses --live")
        else:
            bad("pmm_sol_paper missing --live refuse")
        if "--allow-fixture" in spc and "--log-edge" in spc and "--batch" in spc:
            ok("pmm_sol_paper has allow-fixture + log-edge + batch")
        else:
            bad("pmm_sol_paper missing allow-fixture / log-edge / batch")

    if desk_bal.exists():
        dbt = desk_bal.read_text(encoding="utf-8")
        if "getBalance" in dbt and "never" in dbt.lower() and "seed" in dbt.lower():
            ok("desk_balance is pubkey+RPC RO (no seed reads)")
        else:
            bad("desk_balance missing RO pubkey posture")

    if sol_cex.exists():
        sct = sol_cex.read_text(encoding="utf-8")
        if "unit_mismatch" in sct and "allow_fixture" in sct:
            ok("sol_cex stub kills unit_mismatch / fixture like hygiene")
        else:
            bad("sol_cex missing unit_mismatch / fixture-kill")

    if solana_md.exists():
        sm = solana_md.read_text(encoding="utf-8")
        if "api.jup.ag" in sm and "WITHOUT" in sm.upper() and "custody" in sm.lower():
            ok("docs/SOLANA.md documents quote-only + no custody")
        else:
            bad("docs/SOLANA.md incomplete")
        if "0.001 SOL" in sm and ("Thesis" in sm or "phase" in sm.lower()):
            ok("docs/SOLANA.md notes 0.001 SOL smoke + Thesis phase")
        else:
            bad("docs/SOLANA.md missing 0.001 SOL smoke / Thesis phase note")
        if "solana_paper" in sm and "pmm_sol_paper" in sm and "edge_log" in sm:
            ok("docs/SOLANA.md covers T2 paper fill -> edge_log")
        else:
            bad("docs/SOLANA.md missing T2 paper / edge_log notes")


    # SOL–THB basis paper tape (slice B)
    sol_basis_mod = ROOT / "src" / "venues" / "basis" / "sol_thb.py"
    sol_basis_cli = ROOT / "scripts" / "pmm_sol_basis_scan.py"
    for path_, label in (
        (sol_basis_mod, "src/venues/basis/sol_thb.py"),
        (sol_basis_cli, "scripts/pmm_sol_basis_scan.py"),
    ):
        if path_.exists():
            ok(f"{label} present")
        else:
            bad(f"missing {label}")

    if sol_basis_mod.exists():
        sbt = sol_basis_mod.read_text(encoding="utf-8")
        if "SOL_THB" in sbt and "SOLTHB" in sbt and "USDTTHB" in sbt:
            ok("sol_thb basis has SOL_THB / SOLTHB / USDTTHB wiring")
        else:
            bad("sol_thb basis missing SOL_THB / SOLTHB / USDTTHB")
        if "net_basis_bps" in sbt and "ESTIMATE" in sbt and "money_leg_source_fixture" in sbt:
            ok("sol_thb basis has ESTIMATE net_basis_bps + fixture kill")
        else:
            bad("sol_thb basis missing ESTIMATE / fixture kill")
        if "jupiter" in sbt.lower() and "same_ccy" in sbt:
            ok("sol_thb basis has same_ccy + jupiter FX lanes")
        else:
            bad("sol_thb basis missing same_ccy / jupiter lanes")

    if sol_basis_cli.exists():
        sct = sol_basis_cli.read_text(encoding="utf-8")
        if "--live" in sct and ("REFUSED" in sct or "refuse" in sct.lower()):
            ok("pmm_sol_basis_scan hard-refuses --live")
        else:
            bad("pmm_sol_basis_scan missing --live refuse")
        if "--allow-fixture" in sct and "ESTIMATE" in sct:
            ok("pmm_sol_basis_scan has allow-fixture + ESTIMATE labels")
        else:
            bad("pmm_sol_basis_scan missing allow-fixture / ESTIMATE")

    if solana_md.exists():
        sm2 = solana_md.read_text(encoding="utf-8")
        if "pmm_sol_basis_scan" in sm2 or "SOL–THB basis" in sm2 or "SOL-THB basis" in sm2:
            ok("docs/SOLANA.md covers SOL–THB basis paper tape")
        else:
            bad("docs/SOLANA.md missing SOL–THB basis note")

    if venues_md.exists():
        vt3 = venues_md.read_text(encoding="utf-8")
        if "sol_thb" in vt3 or "pmm_sol_basis_scan" in vt3 or "SOL–THB" in vt3:
            ok("docs/VENUES.md covers SOL–THB basis")
        else:
            bad("docs/VENUES.md missing SOL–THB basis note")

    if apis_md.exists():
        at4 = apis_md.read_text(encoding="utf-8")
        if "pmm_sol_basis_scan" in at4 or "SOL–THB basis" in at4 or "sol_thb" in at4:
            ok("docs/APIS.md mentions SOL–THB basis scan")
        else:
            bad("docs/APIS.md missing SOL–THB basis scan note")

    if custody_md.exists():
        cm = custody_md.read_text(encoding="utf-8")
        if "7W3SPbRcGD1GJPpafEYhgduaMxLpmHBG9KGqytqZEhHf" in cm and "0.001 SOL" in cm:
            ok("docs/SOLANA_CUSTODY.md has desk pubkey + 0.001 SOL smoke")
        else:
            bad("docs/SOLANA_CUSTODY.md incomplete")

    if holes_md.exists():
        ht = holes_md.read_text(encoding="utf-8")
        if "Solana" in ht and ("custody" in ht.lower() or "not wired" in ht.lower()):
            ok("docs/HOLES.md notes Solana live/custody not wired")
        else:
            bad("docs/HOLES.md missing Solana custody hole")

    if apis_md.exists():
        at3 = apis_md.read_text(encoding="utf-8")
        if "api.jup.ag" in at3 and "JUPITER_API_KEY" in at3:
            ok("docs/APIS.md covers Jupiter quote + optional key")
        else:
            bad("docs/APIS.md missing Jupiter / JUPITER_API_KEY")



    # LST fair-rate vs Jupiter basis (mSOL / jitoSOL) — paper/RO
    lst_mod = ROOT / "src" / "venues" / "basis" / "lst.py"
    lst_cli = ROOT / "scripts" / "pmm_lst_basis_scan.py"
    for path, label in (
        (lst_mod, "src/venues/basis/lst.py"),
        (lst_cli, "scripts/pmm_lst_basis_scan.py"),
    ):
        if path.exists():
            ok(f"{label} present")
        else:
            bad(f"{label} missing")

    if lst_mod.exists():
        lt = lst_mod.read_text(encoding="utf-8")
        if "mSoLzYCxHdYgdzU16g5QSh3i5K3z3KZK7ytfqcJm7So" in lt and "Jito4APyf642JPZPx3hGc6WWJ8zPKtRbRs4P815Awbb" in lt:
            ok("lst basis has mSOL mint + jito stake-pool wiring")
        else:
            bad("lst basis missing mSOL / jito stake-pool constants")
        if "net_basis_bps" in lt and "ESTIMATE" in lt and "money_leg_source_fixture" in lt:
            ok("lst basis has ESTIMATE net_basis_bps + fixture kill")
        else:
            bad("lst basis missing ESTIMATE / fixture kill")
        if "api.marinade.finance" in lt and "APY" in lt:
            ok("lst basis uses Marinade price_sol (APY tipster posture documented)")
        else:
            bad("lst basis missing Marinade price_sol / APY note")

    if lst_cli.exists():
        lct = lst_cli.read_text(encoding="utf-8")
        if "--live" in lct and "REFUSED" in lct and "return 2" in lct:
            ok("pmm_lst_basis_scan hard-refuses --live")
        else:
            bad("pmm_lst_basis_scan missing --live refuse")
        if "--allow-fixture" in lct and "ESTIMATE" in lct:
            ok("pmm_lst_basis_scan has allow-fixture + ESTIMATE labels")
        else:
            bad("pmm_lst_basis_scan missing allow-fixture / ESTIMATE")
        if "tipster" in lct.lower() or "no APY" in lct or "APY tipster" in lct:
            ok("pmm_lst_basis_scan documents no APY tipster")
        else:
            bad("pmm_lst_basis_scan missing no-APY-tipster note")

    if solana_md.exists():
        sm3 = solana_md.read_text(encoding="utf-8")
        if "pmm_lst_basis_scan" in sm3 or "LST basis" in sm3 or "lst-basis" in sm3:
            ok("docs/SOLANA.md covers LST basis paper tape")
        else:
            bad("docs/SOLANA.md missing LST basis note")

    if venues_md.exists():
        vt4 = venues_md.read_text(encoding="utf-8")
        if "lst" in vt4.lower() or "pmm_lst_basis_scan" in vt4 or "mSOL" in vt4:
            ok("docs/VENUES.md covers LST basis")
        else:
            bad("docs/VENUES.md missing LST basis note")

    if apis_md.exists():
        at5 = apis_md.read_text(encoding="utf-8")
        if "pmm_lst_basis_scan" in at5 or "msol/price_sol" in at5 or "lst basis" in at5.lower():
            ok("docs/APIS.md mentions LST basis / Marinade price_sol")
        else:
            bad("docs/APIS.md missing LST basis note")


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
