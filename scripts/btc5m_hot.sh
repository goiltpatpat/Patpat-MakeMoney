#!/usr/bin/env bash
# Patpat-MakeMoney hot start — paper-first via pmm/btc5m ctl
set -euo pipefail

PROFILE="${1:-desk}"
LIVE_FLAG="${2:-}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CTL="$SCRIPT_DIR/pmm_ctl.sh"
[[ -x "$CTL" ]] || CTL="$SCRIPT_DIR/btc5m_ctl.sh"

if [[ "$PROFILE" != "desk" && "$PROFILE" != "conservative" && "$PROFILE" != "aggressive" ]]; then
  echo "Usage: $0 [desk|conservative|aggressive] [--live]"
  exit 2
fi

if [[ -n "$LIVE_FLAG" && "$LIVE_FLAG" != "--live" && "$LIVE_FLAG" != "--execute" ]]; then
  echo "Usage: $0 [desk|conservative|aggressive] [--live]"
  exit 2
fi

if [[ -n "$LIVE_FLAG" ]]; then
  exec "$CTL" start --profile "$PROFILE" --live
else
  exec "$CTL" start --profile "$PROFILE"
fi
