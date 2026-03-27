#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# railway_start.sh — LEGACY local-dev / all-in-one startup script.
#
# ⚠️  This script is NOT used by Railway production deployments.
#    Railway services each have a dedicated start script under deploy/railway/:
#      API service:         deploy/railway/start_api.sh   (gunicorn app:app)
#      Engine service:      deploy/railway/start_engine.sh
#      Ingest service:      deploy/railway/start_ingest.sh
#      Orchestrator:        deploy/railway/start_orchestrator.sh
#      Migrator (one-shot): deploy/railway/start_migrator.sh
#      Workers:             deploy/railway/start_worker.sh
#
# This script starts main.py which runs ALL services in one process
# (RUN_MODE=all) — useful for local development only.
# ---------------------------------------------------------------------------
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"

if [[ -z "${DASHBOARD_JWT_SECRET:-}" || ${#DASHBOARD_JWT_SECRET} -lt 32 ]]; then
  echo "[startup] WARNING: DASHBOARD_JWT_SECRET is missing/weak (<32 chars). JWT auth will fail closed." >&2
fi

# Migration ownership is delegated to the dedicated migrator service.
if [[ -z "${DATABASE_URL:-}" ]]; then
  echo "[startup] WARNING: DATABASE_URL not set — DB-backed features may be degraded." >&2
fi

exec python main.py
