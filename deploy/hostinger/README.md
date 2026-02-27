# Hostinger VPS Deployment Guide

Complete step-by-step guide for deploying TUYUL FX WOLF 15-LAYER SYSTEM on Hostinger VPS.

---

## Prerequisites

- Hostinger VPS (Ubuntu 20.04 or 22.04)
- Root/sudo access
- Domain name pointed to your VPS IP
- GitHub repository access
- API keys: Finnhub, Telegram (optional)

---

## Part 1: Initial VPS Setup

### Step 1: Connect to VPS

```bash
ssh root@your-vps-ip
```

### Step 2: Run Initial Setup Script

```bash
# Download and run setup script
cd /tmp
wget https://raw.githubusercontent.com/tjx578/TUYUL-FX-WOLF-15LAYER-SYSTEM/main/deploy/hostinger/setup_vps.sh
chmod +x setup_vps.sh
./setup_vps.sh
```

The script will:

- Update system packages
- Install Python 3.11+, Redis, Nginx, Node.js
- Install Certbot for SSL
- Setup firewall (UFW)
- Create `tuyulfx` user
- Create application directories

### Step 3: Clone Repository

```bash
# Switch to tuyulfx user
sudo su - tuyulfx

# Navigate to app directory
cd /opt/tuyulfx

# Clone repository (use your actual repo URL)
git clone https://github.com/tjx578/TUYUL-FX-WOLF-15LAYER-SYSTEM.git .

# Create Python virtual environment
python3.11 -m venv venv
source venv/bin/activate

# Install Python dependencies
pip install --upgrade pip
pip install -r requirements.txt
```

### Step 4: Configure Environment

```bash
# Copy example env file
cp .env.example .env

# Edit .env with your credentials
nano .env
```

**Important environment variables:**

```bash
APP_ENV="prod"
TRADING_MODE="paper"  # or "live" when ready
TIMEZONE="Asia/Singapore"

# Finnhub API
FINNHUB_API_KEY="your_finnhub_api_key"

# Redis
REDIS_URL="redis://localhost:6379/0"

# Telegram (optional)
TELEGRAM_ENABLED="true"
TELEGRAM_BOT_TOKEN="your_bot_token"
TELEGRAM_CHAT_ID="your_chat_id"

# Dashboard
DASHBOARD_ENABLED="true"
DASHBOARD_JWT_SECRET="CHANGE_ME_TO_RANDOM_STRING"
```

Save and exit (Ctrl+X, Y, Enter).

---

## Part 2: Deploy Services

### Step 5: Install Systemd Services

```bash
# Exit from tuyulfx user back to root
exit

# Copy systemd service files
sudo cp /opt/tuyulfx/deploy/hostinger/*.service /etc/systemd/system/

# Reload systemd
sudo systemctl daemon-reload

# Enable services to start on boot
sudo systemctl enable tuyulfx-engine.service
sudo systemctl enable tuyulfx-api.service
sudo systemctl enable tuyulfx-ingest.service
# sudo systemctl enable tuyulfx-dashboard.service  # Enable after Next.js setup

# Start services
sudo systemctl start tuyulfx-engine.service
sudo systemctl start tuyulfx-api.service
sudo systemctl start tuyulfx-ingest.service

# Check service status
sudo systemctl status tuyulfx-engine.service
sudo systemctl status tuyulfx-api.service
sudo systemctl status tuyulfx-ingest.service
```

### Step 6: Configure Nginx

```bash
# Copy nginx config
sudo cp /opt/tuyulfx/deploy/hostinger/nginx.conf /etc/nginx/sites-available/tuyulfx

# Edit config to replace yourdomain.com with your actual domain
sudo nano /etc/nginx/sites-available/tuyulfx

# Enable the site
sudo ln -s /etc/nginx/sites-available/tuyulfx /etc/nginx/sites-enabled/

# Remove default nginx site
sudo rm -f /etc/nginx/sites-enabled/default

# Test nginx config
sudo nginx -t

# Restart nginx
sudo systemctl restart nginx
```

### Step 7: Setup SSL Certificate

```bash
# Request SSL certificate from Let's Encrypt
sudo certbot --nginx -d yourdomain.com -d www.yourdomain.com

# Follow prompts:
# - Enter email address
# - Agree to terms
# - Choose redirect option (2)

# Certbot will automatically:
# - Obtain certificate
# - Update nginx config
# - Setup auto-renewal

# Test auto-renewal
sudo certbot renew --dry-run
```

---

## Part 3: Deploy Next.js Dashboard (Optional)

### Step 8: Setup Next.js Dashboard

```bash
# Switch to tuyulfx user
sudo su - tuyulfx

# Navigate to dashboard directory
cd /opt/tuyulfx/dashboard/nextjs

# Install dependencies
npm install

# Build production bundle
npm run build

# Exit back to root
exit

# Enable and start dashboard service
sudo systemctl enable tuyulfx-dashboard.service
sudo systemctl start tuyulfx-dashboard.service
sudo systemctl status tuyulfx-dashboard.service
```

---

## Part 4: Monitoring & Maintenance

### View Logs

```bash
# Real-time log monitoring
sudo journalctl -u tuyulfx-engine.service -f
sudo journalctl -u tuyulfx-api.service -f
sudo journalctl -u tuyulfx-ingest.service -f

# Log files
tail -f /opt/tuyulfx/logs/engine.log
tail -f /opt/tuyulfx/logs/api.log
tail -f /opt/tuyulfx/logs/ingest.log
```

### Service Management

```bash
# Check service status
sudo systemctl status tuyulfx-engine.service
sudo systemctl status tuyulfx-api.service
sudo systemctl status tuyulfx-ingest.service
sudo systemctl status tuyulfx-dashboard.service

# Restart services
sudo systemctl restart tuyulfx-engine.service
sudo systemctl restart tuyulfx-api.service

# Stop services
sudo systemctl stop tuyulfx-engine.service

# Start services
sudo systemctl start tuyulfx-engine.service
```

### Check Redis

```bash
# Check Redis status
sudo systemctl status redis-server

# Connect to Redis
redis-cli

# Inside Redis CLI:
PING           # Should return PONG
KEYS *         # List all keys
GET wolf15:verdict:EURUSD  # Get specific key
```

### System Health

```bash
# Check API health
curl http://localhost:8000/health

# Check disk space
df -h

# Check memory usage
free -h

# Check CPU usage
top

# Check open ports
sudo netstat -tulpn | grep LISTEN
```

---

## Part 5: Deployment & Backup

### Deploy Updates

```bash
# Switch to tuyulfx user
sudo su - tuyulfx

# Run deployment script
cd /opt/tuyulfx
./deploy/hostinger/deploy.sh
```

The script will:

1. Create backup
2. Pull latest code
3. Update dependencies
4. Rebuild Next.js
5. Restart services
6. Check service health

### Manual Backup

```bash
# Switch to tuyulfx user
sudo su - tuyulfx

# Run backup script
cd /opt/tuyulfx
./deploy/hostinger/backup.sh
```

Backups are stored in `/opt/tuyulfx/backups/` and kept for 7 days.

### Restore from Backup

```bash
# List backups
ls -lh /opt/tuyulfx/backups/

# Extract backup
cd /opt/tuyulfx/backups
tar -xzf 20260210_120000.tar.gz

# Stop services
sudo systemctl stop tuyulfx-engine.service
sudo systemctl stop tuyulfx-api.service
sudo systemctl stop tuyulfx-ingest.service

# Restore files
cp -r 20260210_120000/storage /opt/tuyulfx/
cp 20260210_120000/redis-dump.rdb /var/lib/redis/dump.rdb

# Restart services
sudo systemctl restart redis-server
sudo systemctl start tuyulfx-engine.service
sudo systemctl start tuyulfx-api.service
sudo systemctl start tuyulfx-ingest.service
```

---

## Part 6: Firewall & Security

### Firewall Rules

```bash
# Check UFW status
sudo ufw status

# Allow specific IPs (optional)
sudo ufw allow from 123.45.67.89 to any port 22  # SSH from specific IP

# Rate limiting on SSH
sudo ufw limit 22/tcp
```

### Fail2Ban (Optional)

```bash
# Install fail2ban
sudo apt-get install -y fail2ban

# Enable for SSH
sudo systemctl enable fail2ban
sudo systemctl start fail2ban

# Check status
sudo fail2ban-client status sshd
```

### Update Security

```bash
# Regular system updates
sudo apt-get update
sudo apt-get upgrade -y

# Update Python packages
sudo su - tuyulfx
cd /opt/tuyulfx
source venv/bin/activate
pip list --outdated
pip install --upgrade <package-name>
```

---

## Part 7: Troubleshooting

### Services Won't Start

```bash
# Check detailed service status
sudo systemctl status tuyulfx-engine.service -l

# Check logs
sudo journalctl -u tuyulfx-engine.service --no-pager -n 100

# Check if port is already in use
sudo netstat -tulpn | grep 8000

# Test Python script manually
sudo su - tuyulfx
cd /opt/tuyulfx
source venv/bin/activate
python main.py
```

### API Returns 502 Bad Gateway

```bash
# Check if FastAPI is running
sudo systemctl status tuyulfx-api.service

# Check if port 8000 is listening
sudo netstat -tulpn | grep 8000

# Check nginx error logs
sudo tail -f /var/log/nginx/tuyulfx-error.log
```

### Redis Connection Issues

```bash
# Check Redis status
sudo systemctl status redis-server

# Test Redis connection
redis-cli ping

# Check Redis config
sudo nano /etc/redis/redis.conf

# Restart Redis
sudo systemctl restart redis-server
```

### SSL Certificate Issues

```bash
# Check certificate status
sudo certbot certificates

# Renew certificate manually
sudo certbot renew

# Check nginx SSL config
sudo nginx -t
```

---

## Part 8: Performance Tuning

### Increase Worker Processes

Edit `/etc/systemd/system/tuyulfx-api.service`:

```ini
ExecStart=/opt/tuyulfx/venv/bin/gunicorn api_server:app \
    --workers 4 \           # Increase from 2
    --worker-class uvicorn.workers.UvicornWorker \
    --bind 127.0.0.1:8000
```

Reload and restart:

```bash
sudo systemctl daemon-reload
sudo systemctl restart tuyulfx-api.service
```

### Redis Performance

Edit `/etc/redis/redis.conf`:

```ini
maxmemory 512mb
maxmemory-policy allkeys-lru
```

Restart Redis:

```bash
sudo systemctl restart redis-server
```

---

## Support & Resources

- **GitHub**: <https://github.com/tjx578/TUYUL-FX-WOLF-15LAYER-SYSTEM>
- **Issues**: Open issue on GitHub
- **Documentation**: See `/docs` directory

---

## Quick Reference

### Make Scripts Executable

```bash
chmod +x /opt/tuyulfx/deploy/hostinger/*.sh
```

### Important Paths

- Application: `/opt/tuyulfx`
- Logs: `/opt/tuyulfx/logs`
- Storage: `/opt/tuyulfx/storage`
- Backups: `/opt/tuyulfx/backups`
- Nginx config: `/etc/nginx/sites-available/tuyulfx`
- Systemd services: `/etc/systemd/system/tuyulfx-*.service`

### Important Commands

```bash
# View all TUYUL services
sudo systemctl list-units "tuyulfx-*"

# Restart all services
sudo systemctl restart tuyulfx-{engine,api,ingest,dashboard}.service

# View all logs
sudo journalctl -u "tuyulfx-*" -f
```

---

## Deployment Complete! 🎉

Your TUYUL FX WOLF 15-LAYER SYSTEM is now running on Hostinger VPS with:

- ✅ Python trading engine
- ✅ FastAPI dashboard API
- ✅ Finnhub WebSocket ingest
- ✅ Next.js dashboard (optional)
- ✅ Redis storage
- ✅ Nginx reverse proxy
- ✅ SSL/TLS encryption
- ✅ Systemd auto-restart
- ✅ Automated backups
