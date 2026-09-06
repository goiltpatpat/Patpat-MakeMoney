#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
set -a
source .env
set +a

LOG_FILE="runtime/pm_live_worker.log"

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] graceful_stop: start" >> "$LOG_FILE"

# try close open position up to 3 attempts
for i in 1 2 3; do
  if [[ ! -f runtime/pm_open_position.json ]]; then
    break
  fi
  OUT=$(.venv/bin/python ./scripts/pm_live_exit_manager.py --state runtime/pm_open_position.json 2>>"$LOG_FILE" || true)
  [[ -n "$OUT" ]] && echo "$OUT" >> "$LOG_FILE"
  sleep 2
done

# stop workers
if [[ -f runtime/pm_live_worker.pid ]]; then
  kill "$(cat runtime/pm_live_worker.pid)" 2>/dev/null || true
  rm -f runtime/pm_live_worker.pid
fi
if [[ -f runtime/pm_live_watchdog.pid ]]; then
  kill "$(cat runtime/pm_live_watchdog.pid)" 2>/dev/null || true
  rm -f runtime/pm_live_watchdog.pid
fi
pkill -f 'scripts/pm_live_worker.sh' || true
pkill -f 'scripts/pm_live_watchdog.sh' || true
pkill -f 'src/live/pm_live_trade_runner.py --execute' || true

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] graceful_stop: done" >> "$LOG_FILE"
echo "stopped"
