#!/usr/bin/env bash
set -euo pipefail

# ── Validate Redis connectivity env var ──
if [[ -z "${REDIS_URL:-}" && -z "${REDIS_PRIVATE_URL:-}" && -z "${REDISHOST:-}" ]]; then
  echo "[startup] WARNING: No Redis URL configured (REDIS_URL / REDIS_PRIVATE_URL / REDISHOST). Outbox worker and real-time features will fail." >&2
fi

# ── Migration ownership lives in wolf15-migrator (one-shot) ──
if [[ -z "${DATABASE_URL:-}" ]]; then
  echo "[startup] WARNING: DATABASE_URL not set; DB-backed API routes may fail." >&2
fi

export WOLF15_SERVICE_ROLE="api"

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
