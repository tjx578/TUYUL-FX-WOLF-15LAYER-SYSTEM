#!/usr/bin/env bash
set -euo pipefail

echo "[startup] Ingest service starting — PORT=${PORT:-8082} INGEST_HEALTH_PORT=${INGEST_HEALTH_PORT:-<unset>}"

exec python -m services.ingest.ingest_worker
