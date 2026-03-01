#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"

if [[ -z "${DASHBOARD_JWT_SECRET:-}" || ${#DASHBOARD_JWT_SECRET} -lt 32 ]]; then
  echo "[startup] WARNING: DASHBOARD_JWT_SECRET is missing/weak (<32 chars). JWT auth will fail closed." >&2
fi

PORT="${PORT:-8000}"
WEB_CONCURRENCY="${WEB_CONCURRENCY:-1}"

exec gunicorn api_server:app \
  --bind "0.0.0.0:${PORT}" \
  --workers "${WEB_CONCURRENCY}" \
  --worker-class uvicorn.workers.UvicornWorker \
  --timeout 120 \
  --access-logfile /dev/stdout \
  --error-logfile /dev/stderr \
  --log-level info
