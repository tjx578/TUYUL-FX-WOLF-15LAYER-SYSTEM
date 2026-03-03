#!/usr/bin/env bash
set -euo pipefail

export PYTHONPATH="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

uvicorn dashboard.backend.api:app --host 0.0.0.0 --port 8000
