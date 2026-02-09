#!/bin/bash
echo "📊 Starting Dashboard"
uvicorn dashboard.backend.api:app --host 0.0.0.0 --port 8000
