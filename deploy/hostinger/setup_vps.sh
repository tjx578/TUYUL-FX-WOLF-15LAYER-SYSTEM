#!/bin/bash
#############################################
# VPS Initial Setup Script for Hostinger
# TUYUL FX WOLF 15-LAYER SYSTEM
#############################################

set -e  # Exit on error

echo "========================================"
echo "TUYUL FX - VPS Setup Script"
echo "========================================"

# Update system
echo "[1/10] Updating system packages..."
sudo apt-get update
sudo apt-get upgrade -y

# Install Python 3.11+
echo "[2/10] Installing Python 3.11..."
sudo apt-get install -y python3.11 python3.11-venv python3-pip

# Install Redis
echo "[3/10] Installing Redis..."
sudo apt-get install -y redis-server
sudo systemctl enable redis-server
sudo systemctl start redis-server

# Install Nginx
echo "[4/10] Installing Nginx..."
sudo apt-get install -y nginx
sudo systemctl enable nginx

# Install Certbot for SSL
echo "[5/10] Installing Certbot..."
sudo apt-get install -y certbot python3-certbot-nginx

# Install Node.js 20.x for Next.js dashboard
echo "[6/10] Installing Node.js..."
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt-get install -y nodejs

# Setup firewall (UFW)
echo "[7/10] Configuring firewall..."
sudo ufw allow 22/tcp    # SSH
sudo ufw allow 80/tcp    # HTTP
sudo ufw allow 443/tcp   # HTTPS
sudo ufw --force enable

# Create tuyulfx user
echo "[8/10] Creating tuyulfx user..."
if id "tuyulfx" &>/dev/null; then
    echo "User tuyulfx already exists"
else
    sudo useradd -m -s /bin/bash tuyulfx
    echo "User tuyulfx created"
fi

# Create application directories
echo "[9/10] Creating application directories..."
sudo mkdir -p /opt/tuyulfx
sudo mkdir -p /opt/tuyulfx/logs
sudo mkdir -p /opt/tuyulfx/storage
sudo mkdir -p /opt/tuyulfx/storage/ea_commands
sudo mkdir -p /opt/tuyulfx/storage/ea_state
sudo chown -R tuyulfx:tuyulfx /opt/tuyulfx

# Clone repository (placeholder - you'll do this manually with your credentials)
echo "[10/10] Repository setup..."
echo "========================================="
echo "MANUAL STEP REQUIRED:"
echo "1. Switch to tuyulfx user: sudo su - tuyulfx"
echo "2. Clone repo: cd /opt/tuyulfx && git clone <your-repo-url> ."
echo "3. Create venv: python3.11 -m venv venv"
echo "4. Activate venv: source venv/bin/activate"
echo "5. Install deps: pip install -r requirements.txt"
echo "6. Copy .env: cp .env.example .env"
echo "7. Edit .env with your credentials"
echo "========================================="

echo ""
echo "VPS setup complete!"
echo "Next steps:"
echo "  1. Complete manual repository setup above"
echo "  2. Copy systemd service files to /etc/systemd/system/"
echo "  3. Copy nginx config to /etc/nginx/sites-available/"
echo "  4. Run: sudo systemctl daemon-reload"
echo "  5. Enable and start services"
echo "  6. Setup SSL with: sudo certbot --nginx -d yourdomain.com"
