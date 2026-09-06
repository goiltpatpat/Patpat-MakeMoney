# Runtime truth — Patpat-MakeMoney

Last aligned: 2026-09-06 (impulse/skew gates shipped; paper path dependencies clarified).

## Enforced by `scripts/test_btc_5m_session_exit_sl.py` (always)
- Resolve active BTC 5m market (`btc-updown-5m-<bucket>`)
- Skip if `sec_left < min_entry_seconds_left`
- CLOB best ask UP/DOWN; candidates with ask ≥ `threshold`
- Pick stronger ask side
- On entry/exit, **always** subprocess the external pm-hl runner (`run_open` / `run_close`); `--execute` only appends the live flag — it does **not** skip the external call in dry mode
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
- Prove (offline): `python scripts/pmm_doctor.py` and `python3 -m unittest discover -s tests -v`
- Offline doctor/unit PASS ≠ end-to-end paper session readiness

## Paper session prerequisites (FACT — not self-contained in this repo alone)
1. External stack at `BTC5M_REPO` (default sibling `pm-hl-conservative-plus-repo`) with `.venv` and `src/live/pm_live_trade_runner.py`
2. `py_clob_client` (and other skill runner deps) in the Python used by the skill runner / ctl
3. Reachability: Polymarket Gamma + CLOB (Binance required only if impulse gate enabled)
4. Confirm pm-hl dry mode (no `--execute`) returns parseable JSON without live keys — **unverified** until the stack is present

## Known local limitations
- Runner profiles are hardcoded; YAML daily-loss, maximum-trades, and hedge settings are not consumed.
- `run_open` defaults spread/liquidity environment guards to permissive values; YAML values do not establish execution protection.
- Ledger/human approval is an operating procedure, not a persisted technical approval gate.
- `btc5m_ctl.sh stop` kills the runner process only; it does not cancel orders or close positions.
- The force-close path creates an authenticated client and can cancel token orders without a local `args.execute` check. Reposting does not require cancellation success. External response contracts and these paths require a separate safety review before relying on paper/live isolation.

## External execution stack
- Team fork: `https://github.com/goiltpatpat/pm-hl-conservative-plus-repo` (from Novals83/polymarket-hl-strategy)
- Default local path: `BTC5M_REPO` / sibling `pm-hl-conservative-plus-repo` under the workspace parent (`~/pm-hl-conservative-plus-repo` on this desk)
- Desk patch: runner accepts `--force-side UP|DOWN` so Patpat-MakeMoney owns entry side (HL signal is advisory when force-side is set)
- Paper still invokes this stack on every `run_open` / `run_close`; `--execute` only toggles live

## External / unverified
- End-to-end paper A/B of gate ON vs OFF in a live 5m window; dry JSON fill vs monitor-loop behavior
- End-to-end paper A/B of gate ON vs OFF in a live 5m window

**Note:** `--skew-gate` alone does not require impulse alignment; use `--enable-gates` for strict `impulse_dir == skew_side == entry_side`.


