#!/usr/bin/env bash
set -euo pipefail

exec gunicorn app:app \
  -k uvicorn.workers.UvicornWorker \
  --bind "0.0.0.0:${PORT:-8000}" \
  --workers 2 \
  --timeout 60 \
  --graceful-timeout 30 \
  --keep-alive 5
