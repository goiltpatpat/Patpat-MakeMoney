#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

./scripts/pm_stack.sh up
exec uvicorn src.health_api:app --host 0.0.0.0 --port "${HEALTH_PORT:-8080}"
