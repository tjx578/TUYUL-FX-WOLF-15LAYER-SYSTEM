#!/bin/bash
echo "🐺 Starting TUYUL FX — LIVE ENGINE"

if [ -f "main.py" ]; then
  python main.py
else
  echo "Error: main.py not found in repository root. Please add main.py or update scripts/run_live.sh to point to the correct entrypoint (for example, using 'python -m <module>')."
  exit 1
fi
