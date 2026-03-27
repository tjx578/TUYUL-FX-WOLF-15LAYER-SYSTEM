#!/usr/bin/env bash
set -euo pipefail

# ── Consolidated Trade Service ──
# Runs: Allocation Worker + Execution Worker in one async process.
# Railway probes /healthz on PORT. Both Prometheus metrics endpoints
# run on their own ports (ALLOC_METRICS_PORT, EXEC_METRICS_PORT).

export WOLF15_SERVICE_ROLE="trade"

exec python -m services.trade.runner
