#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
mkdir -p runtime

PID_FILE="runtime/pm_live_worker.pid"
WLOG="runtime/pm_live_watchdog.log"
LOG_FILE="runtime/pm_live_worker.log"
POS_FILE="runtime/pm_open_position.json"
STOP_TS=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

set -a
source .env
set +a

echo "[$STOP_TS] graceful_stop_requested" >> "$WLOG"

touch runtime/pm_watchdog_stop.flag

# stop watchdog first (best effort)
pkill -f "scripts/pm_live_watchdog.sh" 2>/dev/null || true

# if there is an open position, attempt one forced exit-manager cycle before stopping worker
if [[ -f "$POS_FILE" ]]; then
  echo "[$STOP_TS] graceful_stop_attempt_close_open_position" >> "$LOG_FILE"
  .venv/bin/python ./scripts/pm_live_exit_manager.py \
    --state "$POS_FILE" \
    --sl-pct "${PM_SL_PCT:-0.35}" \
    --tp-pct "${PM_TP_PCT:-0.25}" \
    --trail-arm-pct "${PM_TRAIL_ARM_PCT:-0.15}" \
    --trail-giveback-pct "${PM_TRAIL_GIVEBACK_PCT:-0.08}" \
    --time-exit-sec "999999" \
    --force-close \
    >> "$LOG_FILE" 2>&1 || true
fi

# stop worker
if [[ -f "$PID_FILE" ]]; then
  pid=$(cat "$PID_FILE" 2>/dev/null || true)
  if [[ -n "$pid" ]]; then
    kill "$pid" 2>/dev/null || true
    sleep 1
    kill -9 "$pid" 2>/dev/null || true
  fi
  rm -f "$PID_FILE"
fi

pkill -f "scripts/pm_live_worker.sh" 2>/dev/null || true

echo "[$STOP_TS] graceful_stop_completed" >> "$WLOG"
