#!/usr/bin/env bash
# Patpat-MakeMoney team control entrypoint (wraps btc5m_ctl.sh)
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
exec "$SCRIPT_DIR/btc5m_ctl.sh" "$@"
