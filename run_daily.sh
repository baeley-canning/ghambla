#!/usr/bin/env bash
# Daily cycle against the simulated broker.
#
# Simulated, deliberately: seven candidates have failed Gate 0, so there is no
# validated strategy to trade. What this exercises is the plumbing the design
# doc's Gate 2 asks for — reconciliation, journalling, the risk gate, order
# sizing, halts — none of which needs a funded account or a real venue.
#
# Runs after the US close. WSL must be running for cron to fire; a day the
# machine was off leaves no journal entry, which is itself distinguishable from
# a day that ran and halted.
set -euo pipefail
cd "$(dirname "$0")"
exec .venv/bin/python -m ghambla.scheduler \
    --broker simulated \
    --signals momentum \
    >> "logs/scheduler-$(date +%Y-%m).log" 2>&1
