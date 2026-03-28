#!/usr/bin/env bash
set -euo pipefail

# ── Engine-Only Service ──
# Runs the analysis pipeline only (no ingest, no HTTP API).
# Ingest runs as a separate service.

if [[ -z "${DATABASE_URL:-}" ]]; then
	echo "[startup] DATABASE_URL is required for engine preflight." >&2
	exit 1
fi

if [[ -n "${PORT:-}" ]]; then
	export ENGINE_HEALTH_PORT="${PORT}"
fi

export WOLF15_SERVICE_ROLE="engine"
export RUN_MODE="engine-only"
exec python -m services.engine.runner
