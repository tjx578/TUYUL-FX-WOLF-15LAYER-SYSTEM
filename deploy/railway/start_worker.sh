#!/usr/bin/env bash
set -euo pipefail
entry="${WOLF15_WORKER_ENTRY:?WOLF15_WORKER_ENTRY is required}"
exec python -m "$entry"
