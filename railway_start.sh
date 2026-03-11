#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"

if [[ -z "${DASHBOARD_JWT_SECRET:-}" || ${#DASHBOARD_JWT_SECRET} -lt 32 ]]; then
  echo "[startup] WARNING: DASHBOARD_JWT_SECRET is missing/weak (<32 chars). JWT auth will fail closed." >&2
fi

# ── Run Alembic migrations (idempotent — safe to run on every deploy) ──
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

exec python main.py
