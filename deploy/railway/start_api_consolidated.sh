#!/usr/bin/env bash
set -euo pipefail

# Deprecated compatibility locator. It is deliberately API-only: runtime
# orchestration belongs exclusively to the wolf15-orchestrator service.
if [[ "${WOLF15_EMBED_ORCHESTRATOR:-false}" =~ ^(1|true|yes|on)$ ]]; then
  echo "[startup] ERROR: WOLF15_EMBED_ORCHESTRATOR is no longer supported; use wolf15-orchestrator." >&2
  exit 1
fi

exec bash "$(dirname "$0")/start_api.sh"
