#!/usr/bin/env bash
set -euo pipefail

# ── Consolidated API Service ──
# Runs: FastAPI (gunicorn) + Orchestrator (background thread)
#
# The Orchestrator StateManager is a sync polling loop that runs on its own
# daemon thread.  It is imported at gunicorn worker-ready time via an env var
# that signals api_server.py to spawn it.
#
# Railway probes /healthz on the gunicorn port.  The orchestrator's own
# health probe is optional (ORCHESTRATOR_HEALTH_PORT can be set to an
# unused secondary port if needed).

if [[ -z "${REDIS_URL:-}" && -z "${REDIS_PRIVATE_URL:-}" && -z "${REDISHOST:-}" ]]; then
  echo "[startup] WARNING: No Redis URL configured. Real-time features will fail." >&2
fi

if [[ -z "${DATABASE_URL:-}" ]]; then
  echo "[startup] WARNING: DATABASE_URL not set; DB-backed API routes may fail." >&2
fi

export WOLF15_SERVICE_ROLE="api"
export WOLF15_EMBED_ORCHESTRATOR="true"

exec gunicorn app:app \
  -k deploy.uvicorn_worker.UvicornWorker \
  --bind "0.0.0.0:${PORT:-8000}" \
  --workers "${GUNICORN_WORKERS:-1}" \
  --log-level "${GUNICORN_LOG_LEVEL:-info}" \
  --access-logfile /dev/stdout \
  --error-logfile /dev/stdout \
  --timeout 120 \
  --graceful-timeout 30 \
  --keep-alive 5
