# Architecture

## Components

- `src/live/pm_live_trade_runner.py`
  - pulls Hyperliquid candles
  - resolves Polymarket market + token ids
  - applies entry filters
  - submits BUY or CLOSE orders

- `scripts/pm_live_worker.sh`
  - main orchestration loop
  - runs preview/execute
  - persists open-position state
  - calls exit manager every cycle

- `scripts/pm_live_exit_manager.py`
  - evaluates stop-loss / take-profit / trailing / time-exit
  - delegates order placement to `close_engine.py`
  - handles deferred close and escalation debounce

- `scripts/close_engine.py`
  - pre-close size normalization
  - orderbook readiness gate
  - two-phase close path (IOC probe -> limit ladder -> final IOC)

- `scripts/pm_reconcile.py`
  - API truth snapshot for positions, open orders, allowances

- `scripts/pm_exec_summary.py`
  - daily execution summary from runtime logs

- `src/health_api.py`
  - `/health` and `/ready` endpoints for container/orchestrator checks

## Data path

Hyperliquid candles -> signal -> market side -> Polymarket orderbook gate -> CLOB order post -> position state -> exit manager -> reconcile snapshot/dashboard.
