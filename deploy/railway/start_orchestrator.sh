#!/usr/bin/env bash
set -euo pipefail

if [[ -n "${PORT:-}" ]]; then
	export ORCHESTRATOR_HEALTH_PORT="${PORT}"
fi

export WOLF15_SERVICE_ROLE="orchestrator"

exec python -m services.orchestrator.state_manager
