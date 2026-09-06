---
name: btc-5m-patpat-makemoney
description: Patpat-MakeMoney desk skill for BTC 5-minute Up/Down on Polymarket — momentum-near-close (time-left, BTC move, skew), paper-first dry-run by default, controlled sizing, optional micro-hedge. Live --execute only after Ledger desk gate.
---

# BTC 5m · Patpat-MakeMoney

Fork of upstream `btc-5m-live` for the **Patpat-MakeMoney** desk (Ledger Head · Pulse · Grid · Thesis).

## Paths
- Main trading repo: `<your-workspace>/pm-hl-conservative-plus-repo` (or `BTC5M_REPO`)
- Core runner: `src/live/pm_live_trade_runner.py`
- Canonical skill runner: `scripts/test_btc_5m_session_exit_sl.py`
- Skill control: `scripts/btc5m_ctl.sh`
- Compatibility wrapper (deprecated): `scripts/run_btc_5m_threshold_test.py`
- Desk doctrine: `DESK.md`

## Strategy alignment
Use when the desk wants BTC 5m momentum near close:
- Entry focus ~2 minutes left
- Confirm meaningful BTC impulse (~$70–$100)
- Prefer skew-supported direction
- Enter with momentum, not against it
- Optional small opposite hedge on extreme skew

## Operational rules (desk)
- **Default is dry-run** unless `--execute` is set
- Prefer profile **`desk`** (tighter caps than `aggressive`)
- Controlled stake (`--stake-usd`, profile caps)
- If both UP and DOWN clear threshold, take the stronger side
- Keep stop-loss and timing guards on
- **Do not** tip buys/sells or promise returns
- Live path requires Ledger pre-flight + human confirmation

## One-shot paper (default)
From trading repo root:

```bash
.venv/bin/python scripts/test_btc_5m_session_exit_sl.py --profile desk
```

## One-shot live (opt-in)
```bash
.venv/bin/python scripts/test_btc_5m_session_exit_sl.py --profile desk --execute
```

## Profiles
- File: `config/btc_5m_profiles.yaml`
- Presets: `conservative`, `aggressive`, **`desk`** (Patpat-MakeMoney default)

## Hot commands
- `btc5m desk start` (dry unless stack maps execute separately)
- `scripts/btc5m_ctl.sh start --profile desk`
- `scripts/btc5m_ctl.sh report --limit 20`
- `scripts/btc5m_ctl.sh stop`  # kill switch

## Desk report
After a session, produce a Ledger-ready brief (see `DESK.md`): bias, levels/impulse, skew, result, invalidation, confidence.
