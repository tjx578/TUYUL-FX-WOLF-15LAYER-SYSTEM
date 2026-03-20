#!/usr/bin/env bash
set -euo pipefail

if [[ -z "${DATABASE_URL:-}" ]]; then
  echo "[startup] DATABASE_URL is required for wolf15-migrator." >&2
  exit 1
fi

echo "[startup] Running database migrations (alembic upgrade head)..."
python -m alembic upgrade head
echo "[startup] Migration completed successfully."
