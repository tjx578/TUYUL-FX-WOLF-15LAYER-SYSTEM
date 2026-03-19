#!/usr/bin/env bash
set -euo pipefail

# Migration ownership lives in wolf15-migrator (one-shot). Engine only validates readiness.
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
