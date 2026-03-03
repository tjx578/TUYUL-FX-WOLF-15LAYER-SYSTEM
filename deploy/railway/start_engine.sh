#!/usr/bin/env bash
set -euo pipefail

export RUN_MODE="engine-only"
exec python -m services.engine.runner
