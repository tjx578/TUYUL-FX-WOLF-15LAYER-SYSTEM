#!/bin/bash
#############################################
# Deployment/Update Script for TUYUL FX
# Run this script to deploy updates
#############################################

set -e  # Exit on error

APP_DIR="/opt/tuyulfx"
VENV_DIR="$APP_DIR/venv"
DASHBOARD_DIR="$APP_DIR/dashboard/nextjs"

echo "========================================"
echo "TUYUL FX - Deployment Script"
echo "========================================"

# Check if running as tuyulfx user
if [ "$USER" != "tuyulfx" ]; then
    echo "❌ Error: This script must be run as tuyulfx user"
    echo "Run: sudo su - tuyulfx"
    exit 1
fi

# Navigate to app directory
cd "$APP_DIR"

# Backup current version
echo "[1/8] Creating backup..."
BACKUP_DIR="/opt/tuyulfx/backups/$(date +%Y%m%d_%H%M%S)"
mkdir -p "$BACKUP_DIR"
cp -r storage "$BACKUP_DIR/" 2>/dev/null || true
echo "Backup created at: $BACKUP_DIR"

# Pull latest code
echo "[2/8] Pulling latest code from git..."
git fetch origin
git pull origin main

# Update Python dependencies
echo "[3/8] Updating Python dependencies..."
source "$VENV_DIR/bin/activate"
pip install -r requirements.txt --upgrade

# Update Next.js dependencies
echo "[4/8] Updating Next.js dependencies..."
if [ -d "$DASHBOARD_DIR" ]; then
    cd "$DASHBOARD_DIR"
    npm install
    npm run build
    cd "$APP_DIR"
fi

# Restart services
echo "[5/8] Restarting services..."
sudo systemctl restart tuyulfx-engine.service
sudo systemctl restart tuyulfx-api.service
sudo systemctl restart tuyulfx-ingest.service
if [ -d "$DASHBOARD_DIR" ]; then
    sudo systemctl restart tuyulfx-dashboard.service
fi

# Wait for services to start
echo "[6/8] Waiting for services to start..."
sleep 5

# Check service status
echo "[7/8] Checking service status..."
sudo systemctl is-active --quiet tuyulfx-engine.service && echo "✅ Engine: Running" || echo "❌ Engine: Failed"
sudo systemctl is-active --quiet tuyulfx-api.service && echo "✅ API: Running" || echo "❌ API: Failed"
sudo systemctl is-active --quiet tuyulfx-ingest.service && echo "✅ Ingest: Running" || echo "❌ Ingest: Failed"
if [ -d "$DASHBOARD_DIR" ]; then
    sudo systemctl is-active --quiet tuyulfx-dashboard.service && echo "✅ Dashboard: Running" || echo "❌ Dashboard: Failed"
fi

# Test API health
echo "[8/8] Testing API health..."
sleep 2
curl -s http://localhost:8000/health | grep -q "healthy" && echo "✅ API health check passed" || echo "⚠️ API health check failed"

echo ""
echo "========================================"
echo "Deployment complete!"
echo "========================================"
echo "View logs:"
echo "  Engine:    tail -f /opt/tuyulfx/logs/engine.log"
echo "  API:       tail -f /opt/tuyulfx/logs/api.log"
echo "  Ingest:    tail -f /opt/tuyulfx/logs/ingest.log"
echo "  Dashboard: tail -f /opt/tuyulfx/logs/dashboard.log"
echo ""
echo "Service status:"
echo "  sudo systemctl status tuyulfx-engine"
echo "  sudo systemctl status tuyulfx-api"
echo "  sudo systemctl status tuyulfx-ingest"
echo "  sudo systemctl status tuyulfx-dashboard"
