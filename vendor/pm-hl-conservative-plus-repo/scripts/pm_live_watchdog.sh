#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
mkdir -p runtime

WLOG="runtime/pm_live_watchdog.log"
PID_FILE="runtime/pm_live_worker.pid"
WORKER="./scripts/pm_live_worker.sh"
STOP_FLAG="runtime/pm_watchdog_stop.flag"
MAX_STALE_SEC=1800

restart_worker() {
  if [[ -f "$PID_FILE" ]]; then
    old=$(cat "$PID_FILE" || true)
    [[ -n "$old" ]] && kill "$old" 2>/dev/null || true
  fi
  nohup "$WORKER" >/dev/null 2>&1 &
  echo $! > "$PID_FILE"
  echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] restarted worker pid=$(cat "$PID_FILE")" >> "$WLOG"
}

while true; do
  ts="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  need_restart=0

  if [[ -f "$STOP_FLAG" ]]; then
    echo "[$ts] stop_flag_detected_exit" >> "$WLOG"
    exit 0
  fi

  if [[ ! -f "$PID_FILE" ]]; then
    echo "[$ts] pid file missing" >> "$WLOG"
    need_restart=1
  else
    pid=$(cat "$PID_FILE" || true)
    if [[ -z "${pid}" ]] || ! kill -0 "$pid" 2>/dev/null; then
      echo "[$ts] worker not running" >> "$WLOG"
      need_restart=1
    fi
  fi

  if [[ -f runtime/pm_live_worker.log ]]; then
    now=$(date +%s)
    mtime=$(stat -f %m runtime/pm_live_worker.log 2>/dev/null || echo 0)
    age=$((now-mtime))
    if (( age > MAX_STALE_SEC )); then
      echo "[$ts] worker log stale age=${age}s" >> "$WLOG"
      need_restart=1
    fi
  fi

  if (( need_restart == 1 )); then
    restart_worker
  else
    echo "[$ts] ok" >> "$WLOG"
  fi

  sleep 300
done
