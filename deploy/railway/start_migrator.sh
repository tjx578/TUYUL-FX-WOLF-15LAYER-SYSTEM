#!/usr/bin/env bash
set -euo pipefail

if [[ -z "${DATABASE_URL:-}" ]]; then
  echo "[startup] DATABASE_URL is required for wolf15-migrator." >&2
  exit 1
fi

echo "[startup] Running database migrations (alembic upgrade head)..."
python deploy/railway/migration_runner.py
echo "[startup] Migration completed successfully."
