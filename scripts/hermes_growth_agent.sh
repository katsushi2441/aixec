#!/usr/bin/env bash
set -euo pipefail
cd /home/kojima/exdirect/aixec
exec python3 scripts/growth_agent_pipeline.py "$@"

