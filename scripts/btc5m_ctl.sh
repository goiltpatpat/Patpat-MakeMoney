#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SKILL_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
RUNTIME_DIR="$SKILL_ROOT/runtime"
# Patpat-MakeMoney is the sole execution root (no external/vendor sibling).
REPO="${BTC5M_REPO:-$SKILL_ROOT}"
RUNNER="${BTC5M_RUNNER:-$SKILL_ROOT/scripts/test_btc_5m_session_exit_sl.py}"
VENV_PY="$REPO/.venv/bin/python"
ENV_FILE="${BTC5M_ENV_FILE:-$REPO/.env}"

PIDFILE="$RUNTIME_DIR/btc5m.pid"
METAFILE="$RUNTIME_DIR/btc5m.meta.json"
LATEST_LINK="$RUNTIME_DIR/latest.log"

mkdir -p "$RUNTIME_DIR"

usage() {
  cat <<'EOF'
Usage:
  btc5m_ctl.sh start [--profile desk|conservative|aggressive] [--live|--execute] [--entry-timeout-min N] [--stake-usd N] [--threshold N] [--poll-sec N] [--close-retry-max N] [--close-retry-delay-sec N]
  btc5m_ctl.sh status
  btc5m_ctl.sh stop
  btc5m_ctl.sh report [--limit N]
  btc5m_ctl.sh logs

Notes:
- Patpat-MakeMoney: start is PAPER/dry-run by default. Pass --live or --execute for real orders.
- Default profile: desk
- Runtime: ./runtime (skill-isolated)
- Auth/env: .env at repo root (or BTC5M_ENV_FILE)
- Team alias: scripts/pmm_ctl.sh
EOF
}

is_running() {
  if [[ -f "$PIDFILE" ]]; then
    local pid
    pid="$(cat "$PIDFILE" 2>/dev/null || true)"
    [[ -n "$pid" ]] && ps -p "$pid" >/dev/null 2>&1
  else
    return 1
  fi
}

cmd_start() {
  local profile="desk"
  local entry_timeout_min="35"
  local stake_usd=""
  local threshold=""
  local poll_sec="2"
  local close_retry_max="30"
  local close_retry_delay_sec="2"
  local live=0

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --profile) profile="$2"; shift 2;;
      --live|--execute) live=1; shift;;
      --entry-timeout-min) entry_timeout_min="$2"; shift 2;;
      --stake-usd) stake_usd="$2"; shift 2;;
      --threshold) threshold="$2"; shift 2;;
      --poll-sec) poll_sec="$2"; shift 2;;
      --close-retry-max) close_retry_max="$2"; shift 2;;
      --close-retry-delay-sec) close_retry_delay_sec="$2"; shift 2;;
      *) echo "Unknown arg: $1"; usage; exit 2;;
    esac
  done

  if is_running; then
    echo "already_running pid=$(cat "$PIDFILE")"
    return 0
  fi

  local ts log
  ts="$(date -u +%Y%m%dT%H%M%SZ)"
  log="$RUNTIME_DIR/btc5m_${profile}_${ts}.log"

  local -a runner_cmd
  runner_cmd=("$VENV_PY" "$RUNNER" "--profile" "$profile" "--entry-timeout-min" "$entry_timeout_min" "--poll-sec" "$poll_sec" "--close-retry-max" "$close_retry_max" "--close-retry-delay-sec" "$close_retry_delay_sec")
  if [[ "$live" -eq 1 ]]; then
    runner_cmd+=("--execute")
    echo "WARNING: LIVE mode (--execute). Patpat-MakeMoney desk gate required."
  else
    echo "mode=dry-run (paper). Pass --live to execute real orders."
  fi
  [[ -n "$stake_usd" ]] && runner_cmd+=("--stake-usd" "$stake_usd")
  [[ -n "$threshold" ]] && runner_cmd+=("--threshold" "$threshold")

  (
    export PYTHONUNBUFFERED=1
    if [[ -f "$ENV_FILE" ]]; then
      set -a
      # shellcheck disable=SC1090
      source "$ENV_FILE"
      set +a
    fi
    cd "$REPO"
    nohup "${runner_cmd[@]}" >"$log" 2>&1 &
    echo $! >"$PIDFILE"
  )

  ln -sfn "$log" "$LATEST_LINK"
  local pid
  pid="$(cat "$PIDFILE")"

  cat >"$METAFILE" <<JSON
{
  "startedAt": "$(date -u +%FT%TZ)",
  "pid": $pid,
  "profile": "$profile",
  "entryTimeoutMin": $entry_timeout_min,
  "pollSec": $poll_sec,
  "closeRetryMax": $close_retry_max,
  "closeRetryDelaySec": $close_retry_delay_sec,
  "log": "$log",
  "repo": "$REPO",
  "live": $live,
  "team": "Patpat-MakeMoney"
}
JSON

  sleep 1
  if ps -p "$pid" >/dev/null 2>&1; then
    echo "started pid=$pid log=$log"
  else
    echo "failed_to_start (check $log)"
    exit 1
  fi
}

cmd_status() {
  if is_running; then
    local pid
    pid="$(cat "$PIDFILE")"
    echo "running pid=$pid"
    ps -p "$pid" -o pid=,etime=,command=
  else
    echo "stopped"
  fi
  if [[ -f "$METAFILE" ]]; then
    echo "meta=$METAFILE"
  fi
  if [[ -L "$LATEST_LINK" ]]; then
    echo "latest_log=$(readlink "$LATEST_LINK")"
  fi
}

cmd_stop() {
  if ! is_running; then
    echo "already_stopped"
    return 0
  fi
  local pid
  pid="$(cat "$PIDFILE")"
  kill "$pid" || true
  sleep 1
  if ps -p "$pid" >/dev/null 2>&1; then
    kill -9 "$pid" || true
  fi
  rm -f "$PIDFILE"
  echo "stopped pid=$pid"
}

cmd_report() {
  local limit="20"
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --limit) limit="$2"; shift 2;;
      *) echo "Unknown arg: $1"; usage; exit 2;;
    esac
  done
  "$VENV_PY" "$SKILL_ROOT/scripts/btc5m_report.py" --runtime-dir "$RUNTIME_DIR" --limit "$limit"
}

cmd_logs() {
  if [[ -L "$LATEST_LINK" ]]; then
    tail -n 120 "$(readlink "$LATEST_LINK")"
  else
    echo "no_logs"
  fi
}

main() {
  local cmd="${1:-}"
  [[ -z "$cmd" ]] && { usage; exit 2; }
  shift || true
  case "$cmd" in
    start) cmd_start "$@" ;;
    status) cmd_status ;;
    stop) cmd_stop ;;
    report) cmd_report "$@" ;;
    logs) cmd_logs ;;
    *) usage; exit 2 ;;
  esac
}

main "$@"
