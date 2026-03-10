#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"

if [[ -z "${DASHBOARD_JWT_SECRET:-}" || ${#DASHBOARD_JWT_SECRET} -lt 32 ]]; then
  echo "[startup] WARNING: DASHBOARD_JWT_SECRET is missing/weak (<32 chars). JWT auth will fail closed." >&2
fi

# ── Run Alembic migrations (idempotent — safe to run on every deploy) ──
if [[ -n "${DATABASE_URL:-}" ]]; then
  echo "[startup] Running database migrations…"
  python -m alembic upgrade head || {
    echo "[startup] WARNING: Alembic migration failed — app will start but DB-backed features may be degraded." >&2
  }
else
  echo "[startup] DATABASE_URL not set — skipping migrations."
fi

exec python main.py
