#!/usr/bin/env bash
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
