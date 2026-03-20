#!/usr/bin/env bash
set -euo pipefail
entry="${1:-${WOLF15_WORKER_ENTRY:-${WORKER_ENTRY:-}}}"

if [[ -z "$entry" ]]; then
	echo "WOLF15_WORKER_ENTRY is required (or pass module as first argument)" >&2
	exit 1
fi

exec python -m "$entry"
