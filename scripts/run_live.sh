#!/usr/bin/env bash
set -euo pipefail

export PYTHONPATH="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

python main.py
