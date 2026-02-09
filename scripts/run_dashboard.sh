#!/bin/bash
echo "📊 Starting Dashboard"

if [ -z "$1" ]; then
  echo "Usage: $0 <asgi_app_module>"
  echo "Example: $0 myproject.api:app"
  exit 1
fi

uvicorn "$1" --host 0.0.0.0 --port 8000
