#!/usr/bin/env bash
set -euo pipefail

# Railway healthcheck probes the service PORT. Keep ingest health probe on
# that same port to avoid false 503 due to probing the wrong socket.
if [[ -n "${PORT:-}" ]]; then
	export INGEST_HEALTH_PORT="${PORT}"
fi

export WOLF15_SERVICE_ROLE="ingest"

echo "[startup] Ingest service starting — PORT=${PORT:-8082} INGEST_HEALTH_PORT=${INGEST_HEALTH_PORT:-<unset>}"

exec python -m services.ingest.ingest_worker
