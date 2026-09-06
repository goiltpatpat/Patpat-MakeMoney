# Patpat-MakeMoney

Independent desk repository for the **Patpat-MakeMoney** team: multi-venue BTC tape (public data first), with **Bitkub** as the TH primary execution *candidate* (paper skeleton) and **Polymarket** retained as optional/non-primary. Operated paper-first under Ledger.

Derived from [Novals83/5min-btc-polymarket](https://github.com/Novals83/5min-btc-polymarket). This repo is **not** a GitHub fork — see [NOTICE.md](NOTICE.md).

> Not financial advice. Not a tipster. **Dry-run / paper is the default.** Live execution requires an explicit `--live` / `--execute` opt-in after desk pre-flight. No promised returns.

## Team desk

| Role | Agent | Responsibility |
|------|--------|----------------|
| Head | **Ledger** | Prioritize, assign, synthesize, gate live |
| Scout | **Pulse** | CT/FinTwit + wires → intake |
| Structure | **Grid** | Levels, bias, invalidation |
| Catalyst map | **Thesis** | News ↔ chart; falsify unsafe claims |

**Flow:** Pulse / Grid / Thesis → Ledger desk read → optional skill dry-run → human go-ahead → live

Doctrine and session template: [`DESK.md`](DESK.md)

## What this repo is

An OpenClaw-oriented **skill + control surface** for short-horizon BTC 5m momentum-into-close:

- Canonical runner: `scripts/test_btc_5m_session_exit_sl.py`
- Team entry: `scripts/pmm_ctl.sh` (wraps `btc5m_ctl.sh`)
- Safety doctor: `scripts/pmm_doctor.py`
- Optional hard gates: `scripts/pmm_gates.py` (impulse + skew; **default OFF**)

Runtime truth (enforced vs optional): [`docs/RUNTIME.md`](docs/RUNTIME.md)  
Layout: [`docs/STRUCTURE.md`](docs/STRUCTURE.md)

## Strategy — enforced today

1. Resolve the active Polymarket BTC 5m Up/Down slot.
2. Skip if too little time remains (`min_entry_seconds_left`).
3. Read CLOB best asks; if ask ≥ profile threshold, take the **stronger** side.
4. Apply profile sizing / stop-loss / exit-before timing.
5. Open only when `--execute` is set (otherwise paper/dry).

Default profile: **`desk`** (tighter caps than `conservative` / `aggressive`).

### Optional gates (default OFF)

Enable with `--enable-gates` (or `--impulse-gate` / `--skew-gate`):

| Gate | Source | Behavior |
|------|--------|----------|
| Impulse | Binance `BTCUSDT` (bucket-open kline vs now) | Fail-closed; desk min move **$80** |
| Skew | CLOB best asks | Fail-closed; with both gates ON require `impulse_dir == skew_side == entry_side` |
| Max move $100 | Soft flag only | Does **not** hard-reject |

## Quick start

### 1) Clone

```bash
git clone https://github.com/goiltpatpat/Patpat-MakeMoney.git
cd Patpat-MakeMoney
```

Optional reference remote (not a fork parent):

```bash
git remote add upstream https://github.com/Novals83/5min-btc-polymarket.git
```

### 2) Safety checks (no secrets required)

```bash
python scripts/pmm_doctor.py
PYTHONPATH=scripts python -m unittest tests.test_desk_safety tests.test_pmm_gates
```

### 3) Paper path (required before any live)

**Prerequisites**

- Python environment for the runner
- First-party execution runner at `src/live/pm_live_trade_runner.py` (repo-local `.venv`; optional `$BTC5M_REPO` override)
- Credentials only in that stack’s `.env` / `BTC5M_ENV_FILE` (never commit secrets)

```bash
# dry-run — do NOT pass --execute
python scripts/test_btc_5m_session_exit_sl.py --profile desk

# with optional impulse+skew gates still paper
python scripts/test_btc_5m_session_exit_sl.py --profile desk --enable-gates

# ctl (paper by default)
scripts/pmm_ctl.sh start --profile desk
scripts/pmm_ctl.sh status
scripts/pmm_ctl.sh stop   # kill switch
```

### 4) Live (opt-in only)

Only after Ledger pre-flight **and** explicit human confirmation:

```bash
scripts/pmm_ctl.sh start --profile desk --live
# or
python scripts/test_btc_5m_session_exit_sl.py --profile desk --enable-gates --execute
```

## Pre-live checklist

1. `pmm_doctor.py` PASS  
2. Paper dry-run with the intended flags (gates on/off as decided)  
3. Market valid; time window sane  
4. Impulse/skew logs sensible if gates enabled  
5. Stake / daily loss / kill switch known  
6. Human go-ahead recorded  

## Repository map

| Path | Purpose |
|------|---------|
| `DESK.md` | Desk doctrine + Ledger brief template |
| `SKILL.md` / `CONTOUR.md` | Skill contract + runner contour |
| `NOTICE.md` | Independence + upstream attribution |
| `config/btc_5m_profiles.yaml` | `desk` / `conservative` / `aggressive` |
| `scripts/pmm_ctl.sh` | Team control entry (paper-first) |
| `scripts/pmm_gates.py` | Optional impulse/skew gates |
| `scripts/pmm_doctor.py` | Static safety gates |
| `scripts/btc5m_*` | Upstream-compatible internals |
| `tests/` | Desk + gate unit tests |
| `examples/run-example.md` | Command examples |


## Team readiness (paper)

**Ready for team paper ops** on a machine with this checkout + `.venv` (`requirements-exec.txt`):

- `scripts/pmm_ctl.sh start --profile desk` (no `--live`)
- Offline prove: `python scripts/pmm_doctor.py` and `python -m unittest discover -s tests -v`
- Optional gates paper: add `--enable-gates` on the skill runner

**Live path (opt-in):** fill `.env` → `python scripts/pmm_live_preflight.py` → `PMM_LIVE_OK=1` → `scripts/pmm_ctl.sh start --profile desk --live`.
Open guards are desk-tight; cancel-on-force-close is execute-gated. `stop` kills process only.

## Risk notice

Operational / educational infrastructure for the Patpat-MakeMoney desk. Markets can and will lose money. This repository does not guarantee edge, fills, or PnL. Live trading is a gated exception, never the default.

## Attribution

See [NOTICE.md](NOTICE.md). Inspired by / originally derived from [Novals83/5min-btc-polymarket](https://github.com/Novals83/5min-btc-polymarket).
