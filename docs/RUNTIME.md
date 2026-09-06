# Runtime truth — Patpat-MakeMoney

Last aligned: 2026-09-06 (first-party runner + gates; Desktop paper probe verified).

## Enforced by `scripts/test_btc_5m_session_exit_sl.py` (always)
- Resolve active BTC 5m market (`btc-updown-5m-<bucket>`)
- Skip if `sec_left < min_entry_seconds_left`
- CLOB best ask UP/DOWN; candidates with ask ≥ `threshold`
- Pick stronger ask side; pass `--force-side` into the live runner
- On entry/exit, **always** subprocess first-party `src/live/pm_live_trade_runner.py` via `run_open` / `run_close`; `--execute` only appends the live flag — dry mode still invokes the runner (no-fill without live)
- Profile knobs: threshold, stake, stop-loss %, exit-before, timing/poll

## Optional hard gates (DEFAULT OFF — fail-closed when ON)
Enable with `--enable-gates` or `--impulse-gate` / `--skew-gate`.

**Impulse (Binance BTCUSDT):**
- `btc_open` = Binance 1m **open** at bucket `open_ts` parsed from slug (not first mid-slot poll)
- `btc_move_usd = btc_now - btc_open`
- Pass if `abs(move) >= btc_move_usd_min` and direction not FLAT
- desk min default **80**; conservative/aggressive **70**
- `btc_move_usd_max_reference` (100) = soft flag only
- Open kline fail → `skip_impulse_open_unavailable`; last-price/HTTP fail → `skip_impulse_feed_unavailable` (never enter; no last-print age clock yet)

**Skew (CLOB asks):**
- `skew_side` = higher best ask (tie → skip)
- With impulse on: require `impulse_dir == skew_side == entry_side`
- Anti-impulse threshold-only candidates → `skip_threshold_anti_impulse_only`

## Live isolation
- `--execute` / ctl `--live` require `PMM_LIVE_OK=1`
- ctl live also requires `.env` present
- Authenticated cancel only when `execute=True`
- Open path forces desk-tight `PM_MAX_SPREAD=0.03` and `PM_MIN_TOP_ASK_NOTIONAL_USD=30`
- Live day caps via profile `max_trades_per_day` + `daily_max_loss_usdc` (`runtime/desk_day_*.json`)
- Preflight: `scripts/pmm_live_preflight.py`

## Paper-first control paths
- Team entry: `scripts/pmm_ctl.sh` → `btc5m_ctl.sh start` (dry unless `--live|--execute`)
- Execution root: this repository (optional `BTC5M_REPO` override)
- Prove (offline): `python scripts/pmm_doctor.py` and `python3 -m unittest discover -s tests -v`
- Desktop paper probe (2026-09-06): dry open/close JSON OK; session gates OFF → `no_entry_timeout`; gates ON → `skip_impulse_below_min` when move ≪ $80; `execute=false`

## Paper session prerequisites
1. This repo checkout with `.venv` (`requirements-exec.txt`) and `src/live/pm_live_trade_runner.py`
2. `py_clob_client` installed in that `.venv`
3. Reachability: Polymarket Gamma + CLOB (Binance required when impulse gate enabled)
4. Dry open/close return parseable JSON without live keys — **verified** on Desktop paper probe

## Known local limitations
- Runner profiles are hardcoded; YAML daily-loss, maximum-trades, and hedge settings are not consumed by the skill runner.
- `run_open` defaults some spread/liquidity env guards to permissive values.
- Ledger/human approval is an operating procedure, not a persisted technical approval gate.
- `btc5m_ctl.sh stop` kills the runner process only; it does not cancel orders or close positions.
- Force-close / authenticated cancel paths need a separate safety review before treating paper/live isolation as complete for live ops.
- Dry mode does not create fills (`order_post_result`); monitor/exit loop after a real open is live-path only.

## Team execution surface
- First-party runner: `src/live/pm_live_trade_runner.py` (lineage: Novals83/polymarket-hl-strategy)
- `--force-side UP|DOWN` → desk owns entry side (HL advisory when force-side set)
- Sole GitHub SoT: https://github.com/goiltpatpat/Patpat-MakeMoney

**Note:** `--skew-gate` alone does not require impulse alignment; use `--enable-gates` for strict `impulse_dir == skew_side == entry_side`.
