# BTC 5m Skill Contour — Patpat-MakeMoney

Single source of truth for runners on the team fork.

## Multi-venue data path (Phase 1)
- Tape CLI: scripts/pmm_tape.py
- Venues package: src/venues/ (public BTC, 1inch quotes, Bitkub paper)
- Venue doctrine: docs/VENUES.md
- Sequence: data layer → Bitkub paper; Polymarket optional/non-primary

## Canonical execution path (Polymarket skill — optional)
- Strategy runner (canonical): `scripts/test_btc_5m_session_exit_sl.py`
- Team entry: `scripts/pmm_ctl.sh`
- Unified control: `scripts/btc5m_ctl.sh` (paper-first; `--live` to execute) (`start|status|stop|report|logs`)
- Compatibility wrapper (deprecated): `scripts/run_btc_5m_threshold_test.py`
- Chat/start helper: `scripts/btc5m_hot.sh`
- Watch helper: `scripts/watch_btc_5m_threshold_and_enter.sh`
- PnL/report: `scripts/btc5m_report.py`
- Latest-run reporter: `scripts/btc5m_latest_report.py`
- Optional docker: `scripts/btc5m_docker.sh`
- Desk doctrine: `DESK.md`

## Default mode
- Paper / dry-run unless `--execute`
- Prefer profile **`desk`**; doctor: `scripts/pmm_doctor.py`

## External dependency boundary
- Order engine: `src/live/pm_live_trade_runner.py` (this repo)
- Auth: `.env` at repo root (or `BTC5M_ENV_FILE`)

## Runtime artifacts
- Skill-isolated runtime: `skills/btc-5m-live/runtime` (or `./runtime` via ctl)
- Logs: `btc5m_*` naming

## Isolation guidance
- Keep BTC 5m automation scoped to `btc5m-*`
- Point new automation at the canonical runner only
- Kill switch: `scripts/btc5m_ctl.sh stop`

## Upstream
- Parent: https://github.com/Novals83/5min-btc-polymarket
- Sync: `git fetch upstream && git merge upstream/main`

## Runtime truth
- See `docs/RUNTIME.md` for enforced vs doctrine filters.
