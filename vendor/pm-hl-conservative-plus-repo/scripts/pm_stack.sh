#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
mkdir -p runtime

start() {
  # heartbeat
  if [[ -f runtime/pm_heartbeat.pid ]] && kill -0 "$(cat runtime/pm_heartbeat.pid)" 2>/dev/null; then
    echo "heartbeat already running"
  else
    nohup .venv/bin/python scripts/pm_heartbeat_loop.py >/dev/null 2>&1 & echo $! > runtime/pm_heartbeat.pid
    echo "heartbeat started pid=$(cat runtime/pm_heartbeat.pid)"
  fi

  # reconcile loop
  if [[ -f runtime/pm_reconcile_loop.pid ]] && kill -0 "$(cat runtime/pm_reconcile_loop.pid)" 2>/dev/null; then
    echo "reconcile loop already running"
  else
    nohup bash -c 'while true; do .venv/bin/python scripts/pm_reconcile.py --repo . >/dev/null 2>&1 || true; sleep 60; done' >/dev/null 2>&1 & echo $! > runtime/pm_reconcile_loop.pid
    echo "reconcile loop started pid=$(cat runtime/pm_reconcile_loop.pid)"
  fi

  # worker
  if [[ -f runtime/pm_live_worker.pid ]] && kill -0 "$(cat runtime/pm_live_worker.pid)" 2>/dev/null; then
    echo "worker already running"
  else
    nohup ./scripts/pm_live_worker.sh >/dev/null 2>&1 & echo $! > runtime/pm_live_worker.pid
    echo "worker started pid=$(cat runtime/pm_live_worker.pid)"
  fi
}

stop() {
  ./scripts/pm_live_stop_graceful.sh >/dev/null 2>&1 || true
  for f in runtime/pm_heartbeat.pid runtime/pm_reconcile_loop.pid; do
    if [[ -f "$f" ]]; then
      kill "$(cat "$f")" 2>/dev/null || true
      rm -f "$f"
    fi
  done
  pkill -f 'scripts/pm_heartbeat_loop.py' || true
  pkill -f 'scripts/pm_reconcile.py --repo' || true
  echo "stack stopped"
}

status() {
  echo "worker:"; pgrep -fal 'pm_live_worker.sh' || true
  echo "heartbeat:"; pgrep -fal 'pm_heartbeat_loop.py' || true
  echo "reconcile loop:"; pgrep -fal 'pm_reconcile.py --repo' || true
}

case "${1:-status}" in
  up|start) start ;;
  down|stop) stop ;;
  status) status ;;
  restart) stop; start ;;
  *) echo "Usage: $0 {up|down|status|restart}"; exit 1 ;;
esac
