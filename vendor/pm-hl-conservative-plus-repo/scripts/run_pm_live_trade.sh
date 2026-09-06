#!/usr/bin/env bash
set -euo pipefail

# Usage:
#   ./scripts/run_pm_live_trade.sh dry
#   ./scripts/run_pm_live_trade.sh execute
#   ./scripts/run_pm_live_trade.sh close --close-token-id <id> --close-shares <shares>

MODE="${1:-dry}"
shift || true

BASE_CMD=(
  .venv/bin/python src/live/pm_live_trade_runner.py
  --max-notional-usd "${PM_MAX_NOTIONAL_USD:-15}"
)

if [[ "$MODE" == "execute" ]]; then
  "${BASE_CMD[@]}" --execute "$@"
elif [[ "$MODE" == "close" ]]; then
  "${BASE_CMD[@]}" --execute "$@"
else
  "${BASE_CMD[@]}" "$@"
fi
