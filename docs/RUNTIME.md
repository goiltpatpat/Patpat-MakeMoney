# Runtime truth — Patpat-MakeMoney

Last aligned: 2026-09-06 (impulse/skew gates shipped behind flags).

## Enforced by `scripts/test_btc_5m_session_exit_sl.py` (always)
- Resolve active BTC 5m market (`btc-updown-5m-<bucket>`)
- Skip if `sec_left < min_entry_seconds_left`
- CLOB best ask UP/DOWN; candidates with ask ≥ `threshold`
- Pick stronger ask side; open via external runner only if `--execute`
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

## Paper-first control paths
- `scripts/pmm_ctl.sh` / `btc5m_ctl.sh start` → dry unless `--live|--execute`
- Prove: `python scripts/pmm_doctor.py` and `python -m unittest tests.test_desk_safety tests.test_pmm_gates`

## External / unverified
- Sibling `pm-hl-conservative-plus-repo` live readiness
- End-to-end paper A/B of gate ON vs OFF in a live 5m window

**Note:** `--skew-gate` alone does not require impulse alignment; use `--enable-gates` for strict `impulse_dir == skew_side == entry_side`.
