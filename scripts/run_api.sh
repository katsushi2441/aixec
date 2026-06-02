#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [ -f .env ]; then
  set -a
  . ./.env
  set +a
fi
export AIXEC_DB="${AIXEC_DB:-storage/aixec.sqlite}"
export AIXEC_PORT="${AIXEC_PORT:-8081}"
exec python3 scripts/api_server.py
