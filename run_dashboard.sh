#!/usr/bin/env bash
# Keep the read-only dashboard up. Safe to run repeatedly.
#
# Idempotent on purpose: this is wired to cron's @reboot AND may be run by hand,
# and a second process binding the same port would die with EADDRINUSE and leave
# a confusing log rather than an obvious failure.
set -euo pipefail
cd "$(dirname "$0")"
PORT="${GHAMBLA_DASHBOARD_PORT:-8787}"

if .venv/bin/python - "$PORT" <<'PY'
import socket, sys
s = socket.socket(); s.settimeout(1)
try:
    s.connect(("127.0.0.1", int(sys.argv[1]))); sys.exit(0)   # already up
except Exception:
    sys.exit(1)
finally:
    s.close()
PY
then
    echo "$(date -Is) dashboard already listening on $PORT; nothing to do"
    exit 0
fi

mkdir -p logs
nohup .venv/bin/python -m ghambla.dashboard --port "$PORT" >> logs/dashboard.log 2>&1 &
echo "$(date -Is) started dashboard on $PORT (pid $!)"
