#!/usr/bin/env bash
set -euo pipefail

exec python -m services.ingest.ingest_worker
