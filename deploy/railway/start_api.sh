#!/usr/bin/env bash
set -euo pipefail

exec uvicorn api_server:app \
  --host 0.0.0.0 \
  --port "${PORT:-8000}" \
  --workers 2 \
  --loop uvloop \
  --http httptools
