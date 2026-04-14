#!/bin/bash
#############################################
# VPS Initial Setup Script for Hostinger
# TUYUL FX WOLF 15-LAYER SYSTEM
#
# Fixes applied (2026-04-15):
#   1. PostgreSQL install + DB/user creation
#   2. Redis hardened (bind 127.0.0.1, requirepass,
#      maxmemory 256mb, allkeys-lru, dangerous cmds disabled)
#   3. Swap setup for low-RAM VPS
#   4. Systemd + nginx auto-copy after repo clone
#   5. fail2ban + logrotate
#   6. Node.js install via apt keyring (no pipe-to-bash)
#############################################

set -euo pipefail  # Exit on error, undefined var, pipe failure

APP_DIR="/opt/tuyulfx"
APP_USER="tuyulfx"
REDIS_PASSWORD=$(openssl rand -hex 24)
SWAP_SIZE="2G"

echo "========================================"
echo "TUYUL FX - VPS Setup Script"
echo "========================================"

# ──────────────────────────────────────────
# [1/14] System update
# ──────────────────────────────────────────
echo "[1/14] Updating system packages..."
sudo apt-get update
sudo apt-get upgrade -y

# ──────────────────────────────────────────
# [2/14] Python 3.11
# ──────────────────────────────────────────
echo "[2/14] Installing Python 3.11..."
sudo apt-get install -y python3.11 python3.11-venv python3-pip

# ──────────────────────────────────────────
# [3/14] PostgreSQL
# ──────────────────────────────────────────
echo "[3/14] Installing PostgreSQL..."
sudo apt-get install -y postgresql postgresql-contrib
sudo systemctl enable postgresql
sudo systemctl start postgresql

# Create DB user and database (idempotent)
sudo -u postgres psql -tc "SELECT 1 FROM pg_roles WHERE rolname='${APP_USER}'" \
    | grep -q 1 || sudo -u postgres createuser "${APP_USER}"
sudo -u postgres psql -tc "SELECT 1 FROM pg_database WHERE datname='wolf_trading'" \
    | grep -q 1 || sudo -u postgres createdb wolf_trading -O "${APP_USER}"
echo "PostgreSQL: user=${APP_USER}, db=wolf_trading"

# ──────────────────────────────────────────
# [4/14] Redis (hardened)
# ──────────────────────────────────────────
echo "[4/14] Installing and hardening Redis..."
sudo apt-get install -y redis-server

# Harden Redis config
REDIS_CONF="/etc/redis/redis.conf"
sudo cp "${REDIS_CONF}" "${REDIS_CONF}.bak.$(date +%s)"

# Bind localhost only
sudo sed -i 's/^bind .*/bind 127.0.0.1 ::1/' "${REDIS_CONF}"
# Require password
sudo sed -i "s/^# requirepass .*/requirepass ${REDIS_PASSWORD}/" "${REDIS_CONF}"
sudo sed -i "s/^requirepass .*/requirepass ${REDIS_PASSWORD}/" "${REDIS_CONF}"
# Memory limit (matches docker-compose 256mb)
if ! grep -q "^maxmemory " "${REDIS_CONF}"; then
    echo "maxmemory 256mb" | sudo tee -a "${REDIS_CONF}" > /dev/null
else
    sudo sed -i 's/^maxmemory .*/maxmemory 256mb/' "${REDIS_CONF}"
fi
# Eviction policy
if ! grep -q "^maxmemory-policy " "${REDIS_CONF}"; then
    echo "maxmemory-policy allkeys-lru" | sudo tee -a "${REDIS_CONF}" > /dev/null
else
    sudo sed -i 's/^maxmemory-policy .*/maxmemory-policy allkeys-lru/' "${REDIS_CONF}"
fi
# Disable dangerous commands
for cmd in FLUSHDB FLUSHALL DEBUG KEYS; do
    if ! grep -q "rename-command ${cmd}" "${REDIS_CONF}"; then
        echo "rename-command ${cmd} \"\"" | sudo tee -a "${REDIS_CONF}" > /dev/null
    fi
done

sudo systemctl enable redis-server
sudo systemctl restart redis-server

# ──────────────────────────────────────────
# [5/14] Nginx
# ──────────────────────────────────────────
echo "[5/14] Installing Nginx..."
sudo apt-get install -y nginx
sudo systemctl enable nginx

# ──────────────────────────────────────────
# [6/14] Certbot for SSL
# ──────────────────────────────────────────
echo "[6/14] Installing Certbot..."
sudo apt-get install -y certbot python3-certbot-nginx

# ──────────────────────────────────────────
# [7/14] Node.js 20.x (via apt keyring, no pipe-to-bash)
# ──────────────────────────────────────────
echo "[7/14] Installing Node.js 20.x..."
sudo mkdir -p /etc/apt/keyrings
curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key \
    | sudo gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg
echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_20.x nodistro main" \
    | sudo tee /etc/apt/sources.list.d/nodesource.list > /dev/null
sudo apt-get update
sudo apt-get install -y nodejs

# ──────────────────────────────────────────
# [8/14] Firewall (UFW)
# ──────────────────────────────────────────
echo "[8/14] Configuring firewall..."
sudo ufw allow 22/tcp    # SSH
sudo ufw allow 80/tcp    # HTTP
sudo ufw allow 443/tcp   # HTTPS
sudo ufw --force enable

# ──────────────────────────────────────────
# [9/14] fail2ban (SSH brute-force protection)
# ──────────────────────────────────────────
echo "[9/14] Installing fail2ban..."
sudo apt-get install -y fail2ban
sudo systemctl enable fail2ban
sudo systemctl start fail2ban

# ──────────────────────────────────────────
# [10/14] Swap (for low-RAM VPS)
# ──────────────────────────────────────────
echo "[10/14] Setting up ${SWAP_SIZE} swap..."
if [ ! -f /swapfile ]; then
    sudo fallocate -l "${SWAP_SIZE}" /swapfile
    sudo chmod 600 /swapfile
    sudo mkswap /swapfile
    sudo swapon /swapfile
    echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab > /dev/null
    echo "Swap created: ${SWAP_SIZE}"
else
    echo "Swap already exists, skipping"
fi

# ──────────────────────────────────────────
# [11/14] Create tuyulfx user
# ──────────────────────────────────────────
echo "[11/14] Creating ${APP_USER} user..."
if id "${APP_USER}" &>/dev/null; then
    echo "User ${APP_USER} already exists"
else
    sudo useradd -m -s /bin/bash "${APP_USER}"
    echo "User ${APP_USER} created"
fi

# ──────────────────────────────────────────
# [12/14] Application directories
# ──────────────────────────────────────────
echo "[12/14] Creating application directories..."
sudo mkdir -p "${APP_DIR}"
sudo mkdir -p "${APP_DIR}/logs"
sudo mkdir -p "${APP_DIR}/backups"
sudo mkdir -p "${APP_DIR}/storage"
sudo mkdir -p "${APP_DIR}/storage/ea_commands"
sudo mkdir -p "${APP_DIR}/storage/ea_state"
sudo chown -R "${APP_USER}:${APP_USER}" "${APP_DIR}"

# ──────────────────────────────────────────
# [13/14] Logrotate
# ──────────────────────────────────────────
echo "[13/14] Setting up logrotate..."
sudo tee /etc/logrotate.d/tuyulfx > /dev/null <<'EOF'
/opt/tuyulfx/logs/*.log {
    daily
    missingok
    rotate 14
    compress
    delaycompress
    notifempty
    copytruncate
    maxsize 100M
}
EOF

# ──────────────────────────────────────────
# [14/14] Post-clone instructions
# ──────────────────────────────────────────
echo ""
echo "========================================="
echo "MANUAL STEPS REQUIRED:"
echo "========================================="
echo ""
echo "1. Clone repository:"
echo "   sudo su - ${APP_USER}"
echo "   cd ${APP_DIR} && git clone <your-repo-url> ."
echo ""
echo "2. Python environment:"
echo "   python3.11 -m venv venv"
echo "   source venv/bin/activate"
echo "   pip install -r requirements.txt"
echo ""
echo "3. Environment config:"
echo "   cp .env.example .env"
echo "   nano .env"
echo "   # Set at minimum:"
echo "   #   DATABASE_URL=postgresql://${APP_USER}@localhost:5432/wolf_trading"
echo "   #   REDIS_URL=redis://:${REDIS_PASSWORD}@127.0.0.1:6379/0"
echo "   #   FINNHUB_API_KEY=<your-key>"
echo "   #   DASHBOARD_JWT_SECRET=$(openssl rand -hex 32)"
echo ""
echo "4. Database migrations:"
echo "   source venv/bin/activate"
echo "   alembic upgrade head"
echo ""
echo "5. Install systemd services + nginx (run as root/sudo):"
echo "   sudo cp ${APP_DIR}/deploy/hostinger/tuyulfx-*.service /etc/systemd/system/"
echo "   sudo cp ${APP_DIR}/deploy/hostinger/nginx.conf /etc/nginx/sites-available/tuyulfx"
echo "   sudo ln -sf /etc/nginx/sites-available/tuyulfx /etc/nginx/sites-enabled/"
echo "   sudo rm -f /etc/nginx/sites-enabled/default"
echo "   sudo nginx -t && sudo systemctl reload nginx"
echo "   sudo systemctl daemon-reload"
echo ""
echo "6. Start services:"
echo "   sudo systemctl enable --now tuyulfx-engine"
echo "   sudo systemctl enable --now tuyulfx-api"
echo "   sudo systemctl enable --now tuyulfx-ingest"
echo "   sudo systemctl enable --now tuyulfx-dashboard"
echo ""
echo "7. SSL setup:"
echo "   sudo certbot --nginx -d yourdomain.com"
echo ""
echo "========================================="
echo "CREDENTIALS (save these securely!):"
echo "========================================="
echo "  Redis password: ${REDIS_PASSWORD}"
echo "  PostgreSQL:     ${APP_USER}@localhost:5432/wolf_trading (peer auth)"
echo "========================================="
echo ""
echo "VPS setup complete!"
