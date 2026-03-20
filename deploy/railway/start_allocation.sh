#!/usr/bin/env bash
set -euo pipefail

exec python -m allocation.async_worker
