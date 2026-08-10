#!/usr/bin/env bash
# Mark the open book to market during the US session.
#
# Absolute paths and an explicit cd: cron runs from $HOME with a minimal
# environment, so a relative .venv/bin/python silently does nothing.
set -euo pipefail
cd /home/cassius/gambler
mkdir -p logs
exec .venv/bin/python -m ghambla.marktomarket \
    --minutes "${1:-180}" --every-seconds "${2:-300}" \
    >> "logs/mtm-$(date +%Y-%m-%d).log" 2>&1
