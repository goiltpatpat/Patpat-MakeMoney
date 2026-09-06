# Patpat-MakeMoney · BTC 5m Polymarket

**Team fork** of [Novals83/5min-btc-polymarket](https://github.com/Novals83/5min-btc-polymarket) for the **Patpat-MakeMoney** desk.

Owned by: [`goiltpatpat/Patpat-MakeMoney`](https://github.com/goiltpatpat/Patpat-MakeMoney)  
Workspace: `C:\Users\peat_\Desktop\Patpat-MakeMoney`

OpenClaw skill for **BTC 5-minute Up/Down** markets on Polymarket — momentum near expiry, configurable risk, optional micro-hedge.

> Not a tipster. Not financial advice. **Paper / dry-run is the default.** Live `--execute` is opt-in only after desk pre-flight.

## Desk operating model

| Role | Bot | Job |
|------|-----|-----|
| Head | **Ledger** | Decide what to analyze, assign work, synthesize the final read, gate live runs |
| Scout | **Pulse** | CT/FinTwit + wires → intake (matters vs noise) |
| Structure | **Grid** | Levels, timeframe bias, invalidation |
| Catalyst map | **Thesis** | News ↔ chart agree/conflict, next event |

Flow: **Pulse / Grid / Thesis → Ledger desk read → (optional) this skill dry-run → human go-ahead → live**

See [`DESK.md`](DESK.md) for the paste-ready session brief format and kill-switch rules.

## Strategy (Momentum into Close)

**What the runner enforces today (FACT):**
1. Trade BTC 5m Up/Down near expiry on Polymarket.
2. Skip if seconds left &lt; `min_entry_seconds_left` (default 60; desk prefers ~120s window in docs).
3. Read CLOB best asks for UP/DOWN; if ask ≥ profile `threshold`, take the **stronger** side.
4. Optional stop-loss / exit-before timing; live only with `--execute` / `--live` after desk gate.
5. Sizing from profile caps (default profile: **`desk`**).

**Doctrine / planned (NOT hard-gated in `test_btc_5m_session_exit_sl.py` yet):**
- BTC impulse ~$70–$100 in the active interval
- Skew support (enter with momentum, not against flow)
- Extreme-skew micro-hedge (~95/5)

See `docs/RUNTIME.md`. Gates are next after docs alignment.

## Repository structure

See [`docs/STRUCTURE.md`](docs/STRUCTURE.md).

- `DESK.md` — doctrine + Ledger brief template
- `SKILL.md` / `CONTOUR.md` — skill + runner contour
- `config/btc_5m_profiles.yaml` — `desk` (default), `conservative`, `aggressive`
- `scripts/pmm_ctl.sh` — **team entry** (paper-first)
- `scripts/pmm_doctor.py` + `tests/` — safety gates before merge/live
- `scripts/btc5m_*` — upstream-compatible internals

## Deploy / Run

### Prerequisites

- OpenClaw environment
- Polymarket execution stack at `<your-workspace>/pm-hl-conservative-plus-repo` (or `BTC5M_REPO`)
- Python venv for runners
- API credentials **outside** this repo (never commit secrets)

### Clone (team)

```bash
git clone https://github.com/goiltpatpat/Patpat-MakeMoney.git
cd Patpat-MakeMoney
git remote add upstream https://github.com/Novals83/5min-btc-polymarket.git
```

### Paper-first (required first path)

```bash
# dry-run — NO --execute
.venv/bin/python scripts/test_btc_5m_session_exit_sl.py --profile desk
# or
scripts/pmm_ctl.sh start --profile desk
scripts/pmm_ctl.sh status
scripts/pmm_doctor.py
scripts/pmm_ctl.sh report --limit 20
scripts/pmm_ctl.sh stop
```

### Live (opt-in only)

Only after Ledger desk pre-flight + human confirmation:

```bash
scripts/pmm_ctl.sh start --profile desk --live
# or
.venv/bin/python scripts/test_btc_5m_session_exit_sl.py --profile desk --execute
```

## Execution checklist (before any live order)

1. Market validity — BTC 5m active, not unexpectedly closing
2. Time-to-close — prefer ~120s left
3. Impulse / skew — **desk checklist** (doctrine); not yet enforced by runner code
4. Threshold / stronger-side — **enforced** by runner
5. Liquidity / spread — yaml guards; runner delegates some to external stack (verify)
6. Sizing — stake, max notional, daily loss
7. Stop / exit — stop-loss + `exit_before_sec`
8. Mode — dry-run first; `--execute` only after validation
9. **Desk gate** — Ledger sign-off; kill switch known (`btc5m_ctl.sh stop`)

## Risk controls (desk baseline)

- Prefer **`desk`** profile for Patpat-MakeMoney
- Per-trade risk, daily max loss, max trades/day, max notional
- Quote staleness / spread / liquidity guards
- Optional extreme-skew hedge
- Operational kill switch on repeated API/DNS/execution failures

## Sync from upstream

```bash
git fetch upstream
git checkout main
git merge upstream/main   # or rebase; resolve conflicts carefully
```

## Risk notice

Educational / operational infrastructure for the Patpat-MakeMoney desk.  
No promised returns. No auto-live trading without explicit human go-ahead.

## Attribution

Upstream: [Novals83/5min-btc-polymarket](https://github.com/Novals83/5min-btc-polymarket) — thank you to the original authors.
