#!/usr/bin/env bash
set -euo pipefail

exec python -m services.orchestrator.state_manager
