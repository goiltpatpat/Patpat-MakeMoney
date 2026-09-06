#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
mkdir -p runtime

STATE_FILE="runtime/pm_live_worker_last_market.txt"
POS_FILE="runtime/pm_open_position.json"
PENDING_FILE="runtime/pm_pending_entry.json"
LOG_FILE="runtime/pm_live_worker.log"
JOURNAL_FILE="runtime/trade_journal.jsonl"

set -a
source .env
set +a

append_journal() {
  local kind="$1"
  local payload_json="$2"
  if PAYLOAD_JSON="$payload_json" .venv/bin/python - "$kind" "$JOURNAL_FILE" <<'PY'
import json,datetime,sys,os
kind=sys.argv[1]
out_path=sys.argv[2]
raw=os.environ.get("PAYLOAD_JSON", "")
payload=json.loads(raw) if raw.strip() else {}
evt={"ts": datetime.datetime.utcnow().isoformat()+"Z", "event": kind, "payload": payload}
with open(out_path, "a", encoding="utf-8") as f:
    f.write(json.dumps(evt, ensure_ascii=False)+"\n")
print("ok")
PY
  then
    return 0
  fi
  return 1
}

while true; do
  TS=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
  echo "[$TS] tick" >> "$LOG_FILE"

  # 0) manage open position with stop-loss / take-profit / trailing / time-exit
  EXIT_JSON=$( .venv/bin/python ./scripts/pm_live_exit_manager.py \
      --state "$POS_FILE" \
      --sl-pct "${PM_SL_PCT:-0.35}" \
      --tp-pct "${PM_TP_PCT:-0.25}" \
      --trail-arm-pct "${PM_TRAIL_ARM_PCT:-0.15}" \
      --trail-giveback-pct "${PM_TRAIL_GIVEBACK_PCT:-0.08}" \
      --time-exit-sec "${PM_TIME_EXIT_SEC:-90}" 2>>"$LOG_FILE" || true )
  if [[ -n "$EXIT_JSON" ]]; then
    echo "$EXIT_JSON" >> "$LOG_FILE"
    if printf "%s" "$EXIT_JSON" | python3 -c 'import json,sys; o=json.load(sys.stdin); sys.exit(0 if o.get("action") in ("close","close_failed") else 1)' 2>/dev/null; then
      append_journal "exit" "$EXIT_JSON" || echo "[$TS] journal_write_failed event=exit" >> "$LOG_FILE"
    fi
  else
    echo "[$TS] exit_manager_failed" >> "$LOG_FILE"
  fi

  # 1) preview current market
  PREVIEW=$(./scripts/run_pm_live_trade.sh dry 2>>"$LOG_FILE" || true)
  MARKET=$(printf "%s" "$PREVIEW" | python3 -c 'import sys,json; raw=sys.stdin.read().strip(); print((json.loads(raw).get("market_slug","") if raw else ""))')

  LAST=""
  [[ -f "$STATE_FILE" ]] && LAST=$(cat "$STATE_FILE" || true)

  HAS_POS=0
  [[ -f "$POS_FILE" ]] && HAS_POS=1

  # 2) pending-entry fail-safe: do not re-enter until unknown prior execution window expires
  BLOCK_PENDING=0
  if [[ -f "$PENDING_FILE" ]]; then
    NOW_EPOCH=$(date +%s)
    AGE=$(python3 - <<PY
import json,time
p=json.load(open('$PENDING_FILE'))
print(int(time.time())-int(p.get('ts',0)))
PY
)
    if (( AGE < ${PM_PENDING_TTL_SEC:-180} )); then
      BLOCK_PENDING=1
      echo "[$TS] skip pending_entry age=${AGE}s" >> "$LOG_FILE"
    else
      echo "[$TS] clear stale pending_entry age=${AGE}s" >> "$LOG_FILE"
      rm -f "$PENDING_FILE"
    fi
  fi

  # 3) close-subsystem health guard: if too many recent close_failed, block new entries
  BLOCK_DEGRADED=0
  FAILS_RECENT=$(python3 - <<'PY'
import json
from pathlib import Path
from datetime import datetime, timedelta, timezone
p=Path('runtime/pm_live_exits.log')
if not p.exists():
    print(0); raise SystemExit
now=datetime.now(timezone.utc)
win=timedelta(minutes=float(__import__('os').environ.get('PM_CLOSE_FAIL_WINDOW_MIN','15')))
start=now-win
c=0
for ln in p.read_text(errors='replace').splitlines()[-1500:]:
    try:o=json.loads(ln)
    except: continue
    try:ts=datetime.fromisoformat(str(o.get('ts','')).replace('Z','+00:00'))
    except: continue
    if ts>=start and o.get('action')=='close_failed':
        c+=1
print(c)
PY
)
  if (( FAILS_RECENT >= ${PM_CLOSE_FAIL_THRESHOLD:-6} )); then
    BLOCK_DEGRADED=1
    echo "[$TS] skip degraded_close_subsystem close_failed_recent=${FAILS_RECENT}" >> "$LOG_FILE"
  fi

  if [[ "$HAS_POS" == "0" && "$BLOCK_PENDING" == "0" && "$BLOCK_DEGRADED" == "0" && -n "$MARKET" && "$MARKET" != "$LAST" ]]; then
    echo "[$TS] execute market=$MARKET" >> "$LOG_FILE"
    python3 - <<PY > "$PENDING_FILE"
import json,time
print(json.dumps({'ts': int(time.time()), 'market': '$MARKET'}))
PY

    EXEC_WRAP=$(PM_SIGNATURE_TYPE=2 PM_ORDER_TYPE=FAK PM_MAX_NOTIONAL_USD="${PM_MAX_NOTIONAL_USD:-4}" PM_EXEC_TIMEOUT_SEC="${PM_EXEC_TIMEOUT_SEC:-45}" python3 - <<'PY'
import json,os,subprocess
cmd=["./scripts/run_pm_live_trade.sh","execute"]
env=os.environ.copy()
timeout=float(env.get("PM_EXEC_TIMEOUT_SEC","45"))
try:
    p=subprocess.run(cmd,capture_output=True,text=True,env=env,timeout=timeout)
    out=(p.stdout or '').strip()
    err=(p.stderr or '').strip()
    if not out:
        print(json.dumps({"status":"unknown","reason":"no_json","returncode":p.returncode,"stderr":err[-1000:]}))
    else:
        try:
            obj=json.loads(out)
            post=(obj.get("order_post_result") or {})
            matched=(str(post.get("status","")).lower()=="matched" and post.get("success") is True)
            blocked=bool((obj.get("entry_filters") or {}).get("blocked"))
            status="matched" if matched else ("blocked" if blocked else "failed")
            print(json.dumps({"status":status,"result":obj,"returncode":p.returncode,"stderr":err[-1000:]}))
        except Exception:
            print(json.dumps({"status":"unknown","reason":"invalid_json","returncode":p.returncode,"stdout_tail":out[-1200:],"stderr":err[-800:]}))
except subprocess.TimeoutExpired as e:
    print(json.dumps({"status":"unknown","reason":"timeout","timeout_sec":timeout,"stdout_tail":(e.stdout or '')[-1200:],"stderr":(e.stderr or '')[-800:]}))
PY
)

[[ -n "$EXEC_WRAP" ]] && echo "$EXEC_WRAP" >> "$LOG_FILE"
EXEC_STATUS=$(printf "%s" "$EXEC_WRAP" | python3 -c 'import json,sys; print((json.load(sys.stdin).get("status") or "unknown"))' 2>/dev/null || echo unknown)

if [[ "$EXEC_STATUS" == "matched" ]]; then
      rm -f "$PENDING_FILE"
      EXEC_JSON=$(printf "%s" "$EXEC_WRAP" | python3 -c 'import json,sys; print(json.dumps((json.load(sys.stdin).get("result") or {}), ensure_ascii=False))')
      echo "$MARKET" > "$STATE_FILE"

      if ! printf "%s" "$EXEC_JSON" | PM_SL_BASE="${PM_SL_BASE:-0.30}" PM_SL_VOL_MULT="${PM_SL_VOL_MULT:-220}" PM_SL_MIN="${PM_SL_MIN:-0.20}" PM_SL_MAX="${PM_SL_MAX:-0.50}" \
        PM_TP_BASE="${PM_TP_BASE:-0.20}" PM_TP_VOL_MULT="${PM_TP_VOL_MULT:-180}" PM_TP_MIN="${PM_TP_MIN:-0.12}" PM_TP_MAX="${PM_TP_MAX:-0.45}" \
        PM_TRAIL_ARM_BASE="${PM_TRAIL_ARM_BASE:-0.12}" PM_TRAIL_ARM_VOL_MULT="${PM_TRAIL_ARM_VOL_MULT:-120}" PM_TRAIL_ARM_MIN="${PM_TRAIL_ARM_MIN:-0.08}" PM_TRAIL_ARM_MAX="${PM_TRAIL_ARM_MAX:-0.35}" \
        PM_TRAIL_GIVEBACK_BASE="${PM_TRAIL_GIVEBACK_BASE:-0.06}" PM_TRAIL_GIVEBACK_VOL_MULT="${PM_TRAIL_GIVEBACK_VOL_MULT:-70}" PM_TRAIL_GIVEBACK_MIN="${PM_TRAIL_GIVEBACK_MIN:-0.04}" PM_TRAIL_GIVEBACK_MAX="${PM_TRAIL_GIVEBACK_MAX:-0.20}" \
        PM_TIME_EXIT_SEC="${PM_TIME_EXIT_SEC:-90}" \
        .venv/bin/python ./scripts/pm_position_state_from_exec.py > "$POS_FILE"; then
        echo "[$TS] position_state_build_failed" >> "$LOG_FILE"
      fi
      append_journal "entry_open" "$EXEC_JSON" || echo "[$TS] journal_write_failed event=entry_open" >> "$LOG_FILE"
      echo "[$TS] success market=$MARKET" >> "$LOG_FILE"
elif [[ "$EXEC_STATUS" == "blocked" ]]; then
      rm -f "$PENDING_FILE"
      EXEC_JSON=$(printf "%s" "$EXEC_WRAP" | python3 -c 'import json,sys; print(json.dumps((json.load(sys.stdin).get("result") or {}), ensure_ascii=False))')
      append_journal "entry_blocked" "$EXEC_JSON" || echo "[$TS] journal_write_failed event=entry_blocked" >> "$LOG_FILE"
      echo "[$TS] entry_blocked market=$MARKET" >> "$LOG_FILE"
elif [[ "$EXEC_STATUS" == "failed" ]]; then
      rm -f "$PENDING_FILE"
      EXEC_JSON=$(printf "%s" "$EXEC_WRAP" | python3 -c 'import json,sys; print(json.dumps((json.load(sys.stdin).get("result") or {}), ensure_ascii=False))')
      append_journal "entry_failed" "$EXEC_JSON" || echo "[$TS] journal_write_failed event=entry_failed" >> "$LOG_FILE"
      echo "[$TS] execute_failed market=$MARKET" >> "$LOG_FILE"
else
      # unknown status: keep pending lock for TTL and always journal reason
      append_journal "entry_unknown" "$EXEC_WRAP" || echo "[$TS] journal_write_failed event=entry_unknown" >> "$LOG_FILE"
      echo "[$TS] execute_unknown market=$MARKET" >> "$LOG_FILE"
fi
  else
    echo "[$TS] skip market=$MARKET last=$LAST has_pos=$HAS_POS pending=$BLOCK_PENDING degraded=$BLOCK_DEGRADED" >> "$LOG_FILE"
  fi

  if .venv/bin/python ./scripts/pm_exec_summary.py \
      --tz Europe/Moscow \
      --write-json runtime/pm_exec_summary_today.json \
      --write-md runtime/pm_exec_summary_today.md \
      >> "$LOG_FILE" 2>&1; then
    echo "[$TS] summary_updated runtime/pm_exec_summary_today.{json,md}" >> "$LOG_FILE"
  else
    echo "[$TS] summary_update_failed" >> "$LOG_FILE"
  fi

  sleep "${PM_LOOP_SEC:-60}"
done
