#!/usr/bin/env bash
set -euo pipefail

# ── Dashboard BFF Service ──
# Non-authoritative backend-for-frontend for dashboard aggregation/caching.
# See docs/architecture/dashboard-hybrid-topology.md.
#
# Railway probes /healthz on the gunicorn port.

export APP_ENV="${APP_ENV:-${ENV:-development}}"

if [[ "${APP_ENV,,}" == "production" ]]; then
  if [[ -z "${INTERNAL_API_URL:-}" ]]; then
    echo "[startup] ERROR: INTERNAL_API_URL is required in production." >&2
    exit 1
  fi
elif [[ -z "${INTERNAL_API_URL:-}" ]]; then
  echo "[startup] WARNING: INTERNAL_API_URL not set; BFF will proxy to localhost:8000." >&2
fi

export WOLF15_SERVICE_ROLE="dashboard-bff"

exec gunicorn services.dashboard_bff.main:app \
  -k deploy.uvicorn_worker.UvicornWorker \
  --bind "0.0.0.0:${PORT:-8000}" \
  --workers "${GUNICORN_WORKERS:-1}" \
  --log-level "${GUNICORN_LOG_LEVEL:-info}" \
  --access-logfile /dev/stdout \
  --error-logfile /dev/stdout \
  --timeout 30 \
  --graceful-timeout 10 \
  --keep-alive 5
