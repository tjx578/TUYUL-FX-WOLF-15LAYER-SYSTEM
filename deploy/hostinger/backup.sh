#!/bin/bash
#############################################
# Backup Script for TUYUL FX
# Backs up Redis data, snapshots, and logs
#############################################

set -e  # Exit on error

BACKUP_ROOT="/opt/tuyulfx/backups"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_DIR="$BACKUP_ROOT/$TIMESTAMP"

echo "========================================"
echo "TUYUL FX - Backup Script"
echo "========================================"

# Create backup directory
mkdir -p "$BACKUP_DIR"

# Backup Redis data
echo "[1/4] Backing up Redis data..."
if systemctl is-active --quiet redis-server; then
    redis-cli BGSAVE
    sleep 2
    cp /var/lib/redis/dump.rdb "$BACKUP_DIR/redis-dump.rdb" 2>/dev/null || echo "⚠️ Redis dump not found"
else
    echo "⚠️ Redis service not running"
fi

# Backup storage directory (trade journal, snapshots, EA state)
echo "[2/4] Backing up storage directory..."
if [ -d "/opt/tuyulfx/storage" ]; then
    cp -r /opt/tuyulfx/storage "$BACKUP_DIR/"
    echo "✅ Storage backed up"
else
    echo "⚠️ Storage directory not found"
fi

# Backup logs
echo "[3/4] Backing up logs..."
if [ -d "/opt/tuyulfx/logs" ]; then
    cp -r /opt/tuyulfx/logs "$BACKUP_DIR/"
    echo "✅ Logs backed up"
else
    echo "⚠️ Logs directory not found"
fi

# Backup .env file
echo "[4/4] Backing up .env file..."
if [ -f "/opt/tuyulfx/.env" ]; then
    cp /opt/tuyulfx/.env "$BACKUP_DIR/.env"
    echo "✅ .env backed up"
else
    echo "⚠️ .env file not found"
fi

# Compress backup
echo "Compressing backup..."
cd "$BACKUP_ROOT"
tar -czf "${TIMESTAMP}.tar.gz" "$TIMESTAMP"
rm -rf "$TIMESTAMP"

# Calculate backup size
BACKUP_SIZE=$(du -h "${TIMESTAMP}.tar.gz" | cut -f1)

# Clean up old backups (keep last 7 days)
echo "Cleaning up old backups..."
find "$BACKUP_ROOT" -name "*.tar.gz" -type f -mtime +7 -delete

echo ""
echo "========================================"
echo "Backup complete!"
echo "========================================"
echo "Backup file: $BACKUP_ROOT/${TIMESTAMP}.tar.gz"
echo "Backup size: $BACKUP_SIZE"
echo ""
echo "To restore this backup:"
echo "  cd $BACKUP_ROOT"
echo "  tar -xzf ${TIMESTAMP}.tar.gz"
echo "  sudo systemctl stop tuyulfx-*"
echo "  cp -r ${TIMESTAMP}/storage /opt/tuyulfx/"
echo "  cp ${TIMESTAMP}/redis-dump.rdb /var/lib/redis/dump.rdb"
echo "  sudo systemctl restart redis-server"
echo "  sudo systemctl start tuyulfx-*"
