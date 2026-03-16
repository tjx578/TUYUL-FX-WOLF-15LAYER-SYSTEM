#!/usr/bin/env bash
set -euo pipefail

# ── Validate Redis connectivity env var ──
if [[ -z "${REDIS_URL:-}" && -z "${REDIS_PRIVATE_URL:-}" && -z "${REDISHOST:-}" ]]; then
  echo "[startup] WARNING: No Redis URL configured (REDIS_URL / REDIS_PRIVATE_URL / REDISHOST). Outbox worker and real-time features will fail." >&2
fi

# ── Run Alembic migrations (idempotent — safe on every deploy) ──
if [[ -n "${DATABASE_URL:-}" ]]; then
  echo "[startup] Running database migrations…"
  if python -m alembic upgrade head 2>&1; then
    echo "[startup] Migrations completed successfully."
  else
    echo "[startup] WARNING: Alembic migration failed (exit $?) — app will start but DB-backed features may be degraded." >&2
  fi
else
  echo "[startup] DATABASE_URL not set — skipping migrations."
fi

exec gunicorn app:app \
  -k uvicorn.workers.UvicornWorker \
  --bind "0.0.0.0:${PORT:-8000}" \
  --workers "${GUNICORN_WORKERS:-1}" \
  --log-level "${GUNICORN_LOG_LEVEL:-info}" \
  --access-logfile /dev/stdout \
  --error-logfile /dev/stdout \
  --timeout 120 \
  --graceful-timeout 30 \
  --keep-alive 5
