#!/usr/bin/env bash
set -euo pipefail

# ── Consolidated Engine + Ingest Service ──
# Runs the analysis pipeline AND candle ingest in one process.
# HTTP API is NOT started (that's the separate API service).

if [[ -z "${DATABASE_URL:-}" ]]; then
	echo "[startup] DATABASE_URL is required for engine preflight." >&2
	exit 1
fi

if [[ -n "${PORT:-}" ]]; then
	export ENGINE_HEALTH_PORT="${PORT}"
fi

export WOLF15_SERVICE_ROLE="engine"
export RUN_MODE="engine-ingest"
exec python -m services.engine.runner
