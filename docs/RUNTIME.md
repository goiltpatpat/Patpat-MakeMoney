# Runtime truth — Patpat-MakeMoney

Last aligned: 2026-09-06 (post Grid FACT on entry gates).

## Enforced by `scripts/test_btc_5m_session_exit_sl.py`
- Resolve active BTC 5m market (`btc-updown-5m-<bucket>`)
- Skip if `sec_left < min_entry_seconds_left`
- CLOB best ask UP/DOWN; candidates with ask ≥ `threshold`
- Pick stronger ask side; open via external `pm_live_trade_runner.py` only if `--execute`
- Profile knobs applied: threshold, stake, stop-loss %, exit-before, timing/poll

## Paper-first control paths
- `scripts/pmm_ctl.sh` / `btc5m_ctl.sh start` → dry unless `--live|--execute`
- `btc5m_hot.sh` → desk default, paper unless `--live`
- `watch_btc_5m_threshold_and_enter.sh` → paper unless `--live` / `PMM_LIVE=1`
- Prove gates: `python scripts/pmm_doctor.py`

## Doctrine only (not hard-gated yet)
- BTC impulse ~$70–$100 in interval (`strategy_reference.btc_move_usd_min`)
- Skew-supported direction
- Extreme-skew micro-hedge

These belong in desk checklist / Thesis briefs until a gate PR ships.

## External / unverified here
- Full enforcement of yaml spread/liquidity caps inside external runner
- Secrets in sibling `pm-hl-conservative-plus-repo` `.env`
