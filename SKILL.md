---
name: btc-5m-patpat-makemoney
description: Patpat-MakeMoney desk skill for BTC 5-minute Up/Down on Polymarket — paper-first; enforces time floor + CLOB ask threshold + stronger-side; optional fail-closed impulse/skew gates (default OFF). Live --execute only after Ledger desk gate.
---

# BTC 5m · Patpat-MakeMoney

Independent **Patpat-MakeMoney** desk skill (Ledger Head · Pulse · Grid · Thesis).

## Paths
- Execution root: this repository (override with `BTC5M_REPO` only if needed)
- Live runner: `src/live/pm_live_trade_runner.py`
- Canonical skill runner: `scripts/test_btc_5m_session_exit_sl.py`
- Team control: `scripts/pmm_ctl.sh` → `scripts/btc5m_ctl.sh`
- Compatibility wrapper (deprecated): `scripts/run_btc_5m_threshold_test.py`
- Desk doctrine: `DESK.md`

## Strategy alignment
**Enforced by skill runner:** entry near close (time floor), CLOB ask ≥ threshold, stronger-side pick, profile sizing/SL timing, paper unless `--execute`.

**Optional hard gates (default OFF):** impulse + skew via `--enable-gates` / `--impulse-gate` / `--skew-gate` (fail-closed). Extreme-skew micro-hedge remains doctrine, not implemented by this runner.

## Operational rules (desk)
- **Default is dry-run** unless `--execute` / `--live` is set
- Prefer profile **`desk`**
- Controlled stake (`--stake-usd`, profile caps)
- If both UP and DOWN clear threshold, take the stronger side
- Keep stop-loss and timing guards on
- **Do not** tip buys/sells or promise returns
- Live path requires Ledger pre-flight + human confirmation

## One-shot paper (default)
```bash
.venv/bin/python scripts/test_btc_5m_session_exit_sl.py --profile desk
```

## One-shot paper with gates
```bash
.venv/bin/python scripts/test_btc_5m_session_exit_sl.py --profile desk --enable-gates
```

## One-shot live (opt-in only)
```bash
.venv/bin/python scripts/test_btc_5m_session_exit_sl.py --profile desk --execute
```

## Profiles
- File: `config/btc_5m_profiles.yaml`
- Presets: `conservative`, `aggressive`, **`desk`** (default)

## Hot commands
- `scripts/pmm_ctl.sh start --profile desk`  # paper
- `scripts/pmm_ctl.sh start --profile desk --live`  # live opt-in
- `scripts/pmm_ctl.sh report --limit 20`
- `scripts/pmm_ctl.sh stop`  # process stop (does not cancel orders)

## Desk report
After a session, produce a Ledger-ready brief (see `DESK.md`): bias, levels/impulse, skew, result, invalidation, confidence.
