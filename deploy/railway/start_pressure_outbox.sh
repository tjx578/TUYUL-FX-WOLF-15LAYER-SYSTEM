#!/usr/bin/env bash
set -euo pipefail

export WOLF15_SERVICE_ROLE="pressure-outbox"
python -m services.pressure_outbox.preflight
exec python -m services.pressure_outbox.runner
