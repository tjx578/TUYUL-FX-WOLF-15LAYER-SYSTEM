# Wolf 15-Layer Trading System - Docker Deployment

## Quick Start

### Prerequisites
- Docker 20.10+
- Docker Compose 2.0+

### Build and Run

1. **Build the Docker image:**
   ```bash
   docker-compose build
   ```

2. **Start services (Redis + Wolf App):**
   ```bash
   docker-compose up -d
   ```

3. **Check logs:**
   ```bash
   docker-compose logs -f wolf-app
   ```

4. **Access API:**
   - Health Check: http://localhost:8000/health
   - L12 Verdict: http://localhost:8000/api/v1/l12/{PAIR}

### Service Health

Check service health:
```bash
docker-compose ps
```

### Environment Variables

Create `.env` file (based on `.env.example`):
```env
REDIS_URL=redis://redis:6379/0
FINNHUB_API_KEY=your_key_here
TELEGRAM_BOT_TOKEN=your_token_here
```

### Stop Services

```bash
docker-compose down
```

To remove volumes as well:
```bash
docker-compose down -v
```

## Production Deployment

For production, update `docker-compose.yml`:

1. Add resource limits
2. Configure restart policies
3. Use secrets management
4. Enable TLS/SSL
5. Configure logging drivers

## Monitoring

Services expose health checks:
- Redis: `redis-cli ping`
- Wolf App: `curl http://localhost:8000/health`

## Troubleshooting

**Redis connection issues:**
```bash
docker-compose logs redis
```

**App crashes on startup:**
```bash
docker-compose logs wolf-app
```

**Port conflicts:**
Edit `docker-compose.yml` ports section to use different ports.
