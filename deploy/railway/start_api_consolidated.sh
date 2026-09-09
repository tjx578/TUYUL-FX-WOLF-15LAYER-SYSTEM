#!/usr/bin/env bash
set -euo pipefail

# Deprecated compatibility locator. The canonical entrypoint enforces API-only
# ownership before launching one Gunicorn process.
exec bash "$(dirname "$0")/start_api.sh"
