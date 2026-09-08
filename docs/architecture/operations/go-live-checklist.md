# Wolf-15 Production Go-Live Gates (Railway)

See also: docs/architecture/operations/deploy-order-staging-prod.md for step-by-step deployment order in staging and production.


> Dashboard revision 2026-09-09: repository-only direct-core owner-login changes target the existing Railway frontend `https://wolf15-dashboard-frontend-production.up.railway.app`, port `8080`, and API `https://wolf15-api-production.up.railway.app`. The observed public login still displays `VIEWER JWT`. Password-login/direct-core production acceptance remains HOLD; no deployment, provider-variable mutation, secret provisioning or trading activation was performed.

## 1) Selected architecture

- Browser -> HTTPS -> selected Railway Next.js viewer (port 8080)
- Next server -> HTTPS -> Railway core API; no standalone BFF dependency
- The selected frontend never connects to Redis/Postgres; independent backend services retain their existing state access
- EA bridge private/internal only (not public route exposure)

## 2) Backend ENV (Railway Variables)

The following backend-wide checklist is a review reference, not authorization to change provider variables. Confirm actual API-only runtime and current auth configuration before any separately authorized rollout. Owner-password sessions remain capped at 15 minutes regardless of a legacy token-lifetime setting:

- `ENV=production`
- `DEBUG=false`
- `ENABLE_DEV_ROUTES=false`
- `DASHBOARD_JWT_SECRET=<64+ random chars>`  (only needed by wolf15-api)
- `DASHBOARD_JWT_ALGO=HS256`
- `DASHBOARD_TOKEN_EXPIRE_MIN=60`
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

## 6) Selected Railway frontend configuration

Repository contract, to verify against provider metadata before an authorized deployment:

- `DASHBOARD_MODE=viewer`
- `DASHBOARD_CANONICAL_ORIGIN=https://wolf15-dashboard-frontend-production.up.railway.app`
- `INTERNAL_API_URL=https://wolf15-api-production.up.railway.app` (server-only)
- `PORT=8080`
- API-only core startup; `WOLF15_EMBED_ORCHESTRATOR=false`

No browser API/WS variable, machine key, signing secret or dashboard-BFF URL is required by the selected frontend. Use Secure HttpOnly SameSite sessions and the exact three direct-core GET projections. A legacy Python BFF may still exist independently; this checklist does not assert that it has been stopped or removed from the provider.

See [direct API contract](../dashboard-hybrid-topology.md) and `dashboard/nextjs/next.config.js` for source behavior. Public login remains the observed legacy `VIEWER JWT` page until exact-source deployment and password-login acceptance are separately proven.

## 7) Rate Limit

Redis-backed limiter configured in:

- [api/middleware/rate_limit.py](api/middleware/rate_limit.py)

Supports:

- global per-minute limits
- bucket-specific limits (ws connect / config writes / take actions)
- Redis prefix via `RATE_LIMIT_REDIS_PREFIX`
- trusted proxy behavior via `TRUSTED_PROXY_ENABLED`

## 8) Separate backend WebSocket hardening (not the selected viewer)

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
- [ ] Selected Railway origin, port 8080 and server-only core HTTPS origin match reviewed configuration
- [ ] API-only effective startup is verified with embedded orchestrator disabled
- [ ] Exact source, image and selected-domain identity are bound together
- [ ] Strict build, focused auth/containment tests and source/browser credential scans pass
- [ ] Production password login, wrong-password denial, viewer scope, expiry and logout pass
- [ ] All three production read projections contain only sanitized real core data; failures preserve unknown/HOLD
- [ ] Browser requests contain no machine credentials or JavaScript-readable JWT
- [ ] No BFF/legacy frontend fallback or execution/broker mutation route is reachable
