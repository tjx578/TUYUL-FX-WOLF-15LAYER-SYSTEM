#!/usr/bin/env bash
set -euo pipefail

exec python -m execution.async_worker
