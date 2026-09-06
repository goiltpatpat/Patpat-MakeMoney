#!/usr/bin/env bash
# Patpat-MakeMoney threshold watcher — PAPER by default.
# Pass --live as 5th arg or set PMM_LIVE=1 for real orders.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SKILL_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
WORKSPACE_ROOT="$(cd "$SKILL_ROOT/../.." && pwd)"
REPO="${BTC5M_REPO:-$SKILL_ROOT}"
PY="$SCRIPT_DIR/run_btc_5m_threshold_test.py"  # compatibility wrapper -> canonical runner
LOG="$REPO/runtime/btc_5m_threshold_watch.log"
STATE="$REPO/runtime/btc_5m_threshold_watch.state"

THRESHOLD="${1:-0.75}"
STAKE="${2:-4}"
SLEEP_SEC="${3:-20}"
MAX_MIN="${4:-180}"
MODE_ARG="${5:-}"

LIVE=0
if [[ "${PMM_LIVE:-0}" == "1" || "$MODE_ARG" == "--live" || "$MODE_ARG" == "--execute" ]]; then
  LIVE=1
fi

mkdir -p "$REPO/runtime"
start_ts=$(date +%s)
end_ts=$((start_ts + MAX_MIN*60))

if [[ "$LIVE" -eq 1 ]]; then
  echo "[$(date -u +%FT%TZ)] WARNING LIVE watch threshold=$THRESHOLD stake=$STAKE" | tee -a "$LOG"
else
  echo "[$(date -u +%FT%TZ)] start PAPER watch threshold=$THRESHOLD stake=$STAKE sleep=$SLEEP_SEC max_min=$MAX_MIN" | tee -a "$LOG"
fi

while true; do
  now=$(date +%s)
  if [ "$now" -ge "$end_ts" ]; then
    echo "[$(date -u +%FT%TZ)] timeout reached, stop" | tee -a "$LOG"
    exit 0
  fi

  if [[ "$LIVE" -eq 1 ]]; then
    out=$(cd "$REPO" && .venv/bin/python "$PY" --profile desk --threshold "$THRESHOLD" --stake-usd "$STAKE" --entry-timeout-min 8 --poll-sec 2 --execute 2>&1 || true)
  else
    out=$(cd "$REPO" && .venv/bin/python "$PY" --profile desk --threshold "$THRESHOLD" --stake-usd "$STAKE" --entry-timeout-min 8 --poll-sec 2 2>&1 || true)
  fi
  echo "$out" >> "$LOG"

  # if decision enter and runner returned success/matched -> stop
  if echo "$out" | grep -q '"decision": "enter"'; then
    if echo "$out" | grep -q '"success": true\|"status": "matched"\|"order_post_result"'; then
      echo "[$(date -u +%FT%TZ)] entry attempted, stopping watcher" | tee -a "$LOG"
      echo "entered_at=$(date -u +%FT%TZ)" > "$STATE"
      exit 0
    fi
  fi

  sleep "$SLEEP_SEC"
done
