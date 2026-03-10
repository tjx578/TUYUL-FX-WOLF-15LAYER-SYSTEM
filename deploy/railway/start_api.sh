#!/usr/bin/env bash
set -euo pipefail

# ── Run Alembic migrations (idempotent — safe on every deploy) ──
if [[ -n "${DATABASE_URL:-}" ]]; then
  echo "[startup] Running database migrations…"
  python -m alembic upgrade head || {
    echo "[startup] WARNING: Alembic migration failed — app will start but DB-backed features may be degraded." >&2
  }
else
  echo "[startup] DATABASE_URL not set — skipping migrations."
fi

exec gunicorn app:app \
  -k uvicorn.workers.UvicornWorker \
  --bind "0.0.0.0:${PORT:-8000}" \
  --workers 2 \
  --timeout 60 \
  --graceful-timeout 30 \
  --keep-alive 5
