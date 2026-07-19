#!/usr/bin/env bash
set -euo pipefail

export WOLF15_SERVICE_ROLE="pressure-outbox"
exec python -m services.pressure_outbox.runner
