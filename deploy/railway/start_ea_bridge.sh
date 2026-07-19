#!/usr/bin/env bash
set -euo pipefail

if [[ -z "${DATABASE_URL:-}" ]]; then
  echo "[startup] ERROR: DATABASE_URL is required for the MT5 executor bridge." >&2
  exit 1
fi

auth_secret="${EXECUTOR_BRIDGE_AUTH_SECRET:-}"
signing_secret="${EXECUTOR_COMMAND_SIGNING_SECRET:-}"

if [[ ${#auth_secret} -lt 32 ]]; then
  echo "[startup] ERROR: EXECUTOR_BRIDGE_AUTH_SECRET must be at least 32 characters." >&2
  exit 1
fi

if [[ ${#signing_secret} -lt 32 ]]; then
  echo "[startup] ERROR: EXECUTOR_COMMAND_SIGNING_SECRET must be at least 32 characters." >&2
  exit 1
fi

export WOLF15_SERVICE_ROLE="ea-bridge"

exec gunicorn services.ea_bridge.main:app \
  -k deploy.uvicorn_worker.UvicornWorker \
  --bind "0.0.0.0:${PORT:-8080}" \
  --workers "${EA_BRIDGE_WORKERS:-1}" \
  --log-level "${GUNICORN_LOG_LEVEL:-info}" \
  --access-logfile /dev/stdout \
  --error-logfile /dev/stderr \
  --timeout 60 \
  --graceful-timeout 30 \
  --keep-alive 15
