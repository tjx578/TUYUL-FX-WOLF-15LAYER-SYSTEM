#!/usr/bin/env bash
set -euo pipefail

exec uvicorn services.api.main:app \
  --host 0.0.0.0 \
  --port "${PORT:-8000}" \
  --workers 2 \
  --loop uvloop \
  --http httptools
