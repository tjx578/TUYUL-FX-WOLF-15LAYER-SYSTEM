#!/usr/bin/env bash
set -euo pipefail

# Ensure DB schema is ready before engine boots.
if [[ -n "${DATABASE_URL:-}" ]]; then
	echo "[startup] Running database migrations…"
	python -m alembic upgrade head
	echo "[startup] Migrations completed successfully."
else
	echo "[startup] DATABASE_URL not set — skipping migrations."
fi

export RUN_MODE="engine-only"
exec python -m services.engine.runner
