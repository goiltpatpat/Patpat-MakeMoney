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

Upstream-aligned short-horizon momentum:

1. Trade BTC 5m event markets near expiry.
2. Main entry window: around **2 minutes left**.
3. Confirm BTC has already moved about **$70–$100** in the active interval.
4. Check market skew; if flow supports the move, enter **with** momentum.
5. Sizing from profile caps (desk default: **`desk`** profile — tighter than retail aggressive).
6. Optional micro-hedge when skew is extreme (e.g. 95/5).

This is momentum-following, not mean-reversion.

## Repository structure

- `DESK.md` — Patpat-MakeMoney operating doctrine + Ledger report template
- `SKILL.md` — skill definition and operating rules
- `CONTOUR.md` — canonical runners and dependency boundary
- `config/btc_5m_profiles.yaml` — `conservative`, `aggressive`, **`desk`**
- `scripts/` — runners / ctl / reports
- `examples/` — command examples

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
scripts/btc5m_ctl.sh start --profile desk
scripts/btc5m_ctl.sh status
scripts/btc5m_ctl.sh report --limit 20
scripts/btc5m_ctl.sh stop
```

### Live (opt-in only)

Only after Ledger desk pre-flight + human confirmation:

```bash
.venv/bin/python scripts/test_btc_5m_session_exit_sl.py --profile desk --execute
```

## Execution checklist (before any live order)

1. Market validity — BTC 5m active, not unexpectedly closing
2. Time-to-close — prefer ~120s left
3. Impulse — meaningful BTC move (~$70–$100 ref)
4. Skew — supports direction (do not fade strong momentum by default)
5. Liquidity / spread — pass profile guards
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
