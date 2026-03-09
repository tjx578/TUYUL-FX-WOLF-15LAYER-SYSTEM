#!/usr/bin/env bash
set -euo pipefail

job="${WOLF15_WORKER_JOB:-}"

case "$job" in
  montecarlo)
    exec python -m services.worker.montecarlo_job
    ;;
  regime)
    exec python -m services.worker.regime_recalibration
    ;;
  backtest)
    exec python -m services.worker.nightly_backtest
    ;;
  *)
    echo "[start_worker] invalid or missing WOLF15_WORKER_JOB: '$job'" >&2
    echo "[start_worker] allowed values: montecarlo | regime | backtest" >&2
    exit 2
    ;;
esac
