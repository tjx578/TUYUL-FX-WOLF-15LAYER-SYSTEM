#!/usr/bin/env bash
set -euo pipefail

export PYTHONPATH="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

uvicorn app:app --host 0.0.0.0 --port "${PORT:-8000}" --ws-per-message-deflate
