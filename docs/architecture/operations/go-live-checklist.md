# Wolf-15 Production Go-Live (Vercel + Railway)

See also: docs/architecture/operations/deploy-order-staging-prod.md for step-by-step deployment order in staging and production.

## 1) Final Architecture

- Browser → HTTPS → Vercel (Next.js)
- Vercel → HTTPS (server-to-server) → Railway FastAPI backend
- Backend only service that talks to Redis + Postgres
- EA bridge private/internal only (not public route exposure)

## 2) Backend ENV (Railway Variables)

Set exactly in Railway service variables:

- `ENV=production`
- `DEBUG=false`
- `ENABLE_DEV_ROUTES=false`
- `JWT_SECRET=<64+ random chars>`
- `JWT_ALGORITHM=HS256`
- `JWT_TTL_MINUTES=30`
- `DATABASE_URL=postgresql://...`
- `REDIS_URL=redis://...`
- `RATE_LIMIT_ENABLED=true`
- `RATE_LIMIT_REDIS_PREFIX=ratelimit:`
- `WS_REQUIRE_AUTH=true`
- `WS_PING_INTERVAL=15`
- `WS_HEARTBEAT_TIMEOUT=30`
- `WS_MAX_CONNECTIONS_PER_MIN=10`
- `COMPLIANCE_MODE_DEFAULT=true`
- `CONFIG_LOCK_PROTECTED_FIELDS=true`
- `REQUIRE_ADMIN_PIN_FOR_HIGH_RISK=true`
- `ADMIN_PIN_HASH=<bcrypt hash>`
- `CORS_ORIGINS=https://yourdomain.com`
- `TRUSTED_PROXY_ENABLED=true`
- `FORCE_HTTPS=true`
- `LOG_LEVEL=INFO`
- `AUDIT_LOG_ENABLED=true`

Rules:

- Never put secret values in frontend env.
- Never commit `.env`.

## 3) Railway Runtime

This repo now runs API via Gunicorn worker model in:

- [deploy/railway/start_api.sh](deploy/railway/start_api.sh)

Parameters:

- workers `2`
- timeout `60`
- graceful-timeout `30`
- keep-alive `5`

## 4) Redis Hardening

Railway Redis requirements:

- AUTH required
- private networking only
- persistence ON (AOF)

App usage:

- `redis.from_url(..., decode_responses=True)` already used in app paths
- used for rate limit, WS sessions, active config cache, lockdown key

Namespace examples:

- `cfg:account:acc_123:active`
- `ratelimit:token:xyz`
- `ws:sessions:user_45`
- `system:lockdown`

## 5) Postgres Hardening

Requirements:

- SSL required in `DATABASE_URL`
- backups daily (Railway setting)
- max connections 20–50
- pooled access only

App status:

- async pool already used in [storage/postgres_client.py](storage/postgres_client.py)
- health integrated in [api_server.py](api_server.py#L332)

## 6) Vercel Config

Frontend env:

- `NEXT_PUBLIC_API_BASE_URL=https://api.yourdomain.com`
- `NEXT_PUBLIC_WS_URL=wss://api.yourdomain.com/ws`

Do not store secrets in Vercel public vars.

Frontend config updated:

- [dashboard/nextjs/next.config.js](dashboard/nextjs/next.config.js)

## 7) Rate Limit

Redis-backed limiter configured in:

- [api/middleware/rate_limit.py](api/middleware/rate_limit.py)

Supports:

- global per-minute limits
- bucket-specific limits (ws connect / config writes / take actions)
- Redis prefix via `RATE_LIMIT_REDIS_PREFIX`
- trusted proxy behavior via `TRUSTED_PROXY_ENABLED`

## 8) WebSocket Hardening

Implemented in:

- [api/ws_routes.py](api/ws_routes.py)

Controls:

- handshake auth required when `WS_REQUIRE_AUTH=true`
- heartbeat ping interval via `WS_PING_INTERVAL`
- disconnect on stale heartbeat via `WS_HEARTBEAT_TIMEOUT`
- Redis session keys under `ws:sessions:user_<id>:<connection>`

## 9) Security Layer

Implemented in:

- [api_server.py](api_server.py)

Includes:

- HTTPS redirect middleware (`FORCE_HTTPS`)
- strict CORS from `CORS_ORIGINS` (no wildcard in production)
- CSP + security response headers

## 10) Monitoring Minimum

Health endpoints:

- `GET /healthz` — liveness probe (no deps, no auth)
- `GET /health` — liveness alias (same as /healthz)
- `GET /api/v1/status` — operator diagnostics (JWT-authed)
- `GET /api/v1/status/full` — deep diagnostics (JWT-authed)

Operator status checks:

- Redis connectivity
- Postgres connectivity
- config load status
- engine runtime state
- lockdown state

File:

- [api_server.py](api_server.py#L332)

Recommended Railway alerts:

- high CPU
- high memory
- restart loop
- healthcheck failures
- 429 spike / 403 spike / 5xx spike

## 11) Final Go-Live Verification Checklist

- [ ] `ENV=production`, `DEBUG=false`, `ENABLE_DEV_ROUTES=false`
- [ ] CORS only allows `https://yourdomain.com`
- [ ] all secrets configured only in Railway
- [ ] Redis private + AUTH + persistence enabled
- [ ] Postgres SSL + backups enabled
- [ ] `/api/v1/status` returns Redis + Postgres connected
- [ ] WS auth fails closed without token
- [ ] WS stale clients disconnected <= 30s
- [ ] 429 response triggered when limit exceeded
- [ ] HTTPS redirect active (`FORCE_HTTPS=true`)
- [ ] CSP header present in responses
- [ ] Vercel points to `https://api.yourdomain.com` and `wss://api.yourdomain.com/ws`
