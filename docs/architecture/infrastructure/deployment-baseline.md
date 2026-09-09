# Deployment Topology — TUYUL FX Wolf-15


> Dashboard revision 2026-09-09: repository-only direct-core owner-login changes target the existing Railway frontend `https://wolf15-dashboard-frontend-production.up.railway.app`, port `8080`, and API `https://wolf15-api-production.up.railway.app`. The observed public login still displays `VIEWER JWT`. Password-login/direct-core production acceptance remains HOLD; no deployment, provider-variable mutation, secret provisioning or trading activation was performed.

## Selected dashboard architecture

```text
Browser on selected Railway dashboard origin
  -> Railway Next.js viewer, PORT=8080
  -> same-origin owner-login/session + three GET projections
  -> HTTPS core API (API-only; embedded orchestrator disabled)
  -> existing backend read state

Independent system services retain their own authority boundaries:
  Engine / orchestrator / trade / EA bridge
  Redis: streams, operational cache and heartbeat state
  PostgreSQL: durable configuration, audit, journal and ledger
```

The selected viewer has no route to engine control, broker execution or database mutation. Its legacy standalone Python BFF is disconnected. Broader backend/EA sections below describe separate services, not additional viewer permissions.


---

## Services

| Service | Platform | Purpose |
| --- | --- | --- |
| Dashboard | Railway, port 8080 | Next.js owner-login viewer; three direct core read projections |
| API | Railway | API-only auth and existing read endpoints; no embedded orchestrator for selected login deployment |
| Engine / trade services | Railway | Separate constitutional, risk and execution responsibilities; unchanged by dashboard revision |
| Redis | Railway (managed) | Tick streams, context cache, rate-limit state |
| Postgres | Railway (managed) | Config profiles, journal, account ledger |
| EA bridge | Railway **or** local MT5 host | Receives execution commands from EA, reports fills |

---

## Environment Variables

### Backend (Railway)

```env
# Auth (wolf15-api service only — other services do not use JWT)
DASHBOARD_JWT_SECRET=<random 64-char string>
DASHBOARD_JWT_ALGO=HS256
DASHBOARD_TOKEN_EXPIRE_MIN=60
DASHBOARD_API_KEY=<optional service-to-service key>

# CORS
CORS_ORIGINS=https://dashboard.yourdomain.com

# Redis
REDIS_URL=rediss://:<password>@...
RATE_LIMIT_BACKEND=redis          # use Redis for distributed rate limiting

# Postgres
DATABASE_URL=postgresql+asyncpg://...

# Deployment
ENV=production
FORCE_HTTPS=true
API_DOMAIN=api.yourdomain.com

# Orchestrator runtime (services/orchestrator)
ORCHESTRATOR_CHANNEL=wolf15:orchestrator:commands
ORCHESTRATOR_STATE_KEY=wolf15:orchestrator:state
ORCHESTRATOR_ACCOUNT_STATE_KEY=wolf15:account:state
ORCHESTRATOR_TRADE_RISK_KEY=wolf15:trade:risk
ORCHESTRATOR_LOOP_SLEEP_SEC=0.5
ORCHESTRATOR_COMPLIANCE_INTERVAL_SEC=5
ORCHESTRATOR_HEARTBEAT_INTERVAL_SEC=30
```

Notes for orchestrator ops:

- Channel `ORCHESTRATOR_CHANNEL` dipakai dua arah: command masuk dan status keluar.
- Orchestrator menjalankan compliance tick periodik dari snapshot key account/risk.
- Jika compliance severity `critical` maka mode dipaksa ke `KILL_SWITCH`; severity `warning` ke `SAFE`.

Railway cron note:

- `cronSchedule` di Railway dievaluasi dalam timezone `UTC`; sesuaikan jam nightly/weekly terhadap timezone operasional tim agar tidak ambigu.

### Frontend (selected Railway service)

```env
DASHBOARD_MODE=viewer
DASHBOARD_CANONICAL_ORIGIN=https://wolf15-dashboard-frontend-production.up.railway.app
INTERNAL_API_URL=https://wolf15-api-production.up.railway.app
PORT=8080
NEXT_PUBLIC_TIMEZONE=Asia/Makassar
```

`INTERNAL_API_URL` is server-only, credential-free and HTTPS in production. The frontend needs no public API/WS origin, signing secret, machine API key or dashboard-BFF variable. Changing repository examples does not change provider service variables.

---

## Selected owner-login flow

1. Browser posts username/password to same-origin `/api/auth/owner-login`.
2. Next forwards to core `/api/auth/owner-login`; backend verification issues only a viewer JWT with `read:dashboard`.
3. Next sets the Secure HttpOnly SameSite `wolf15_session` cookie. JavaScript/localStorage never receive the token.
4. The three exact GET projections validate the session against core and forward only an explicit Bearer token server-to-server.
5. Core JSON is projected to safe fields before browser delivery; unknown paths, mutation verbs, raw diagnostics and credentials are rejected or removed.
6. Password-owner access expires within 15 minutes; legacy refresh/reissuance cannot extend it. Logout clears browser access.

The earlier backend-wide token settings are not permission to extend the owner-password session. See [direct API contract](../dashboard-hybrid-topology.md). Production credentials and acceptance checks remain separate authorized operations.

---

## Rate Limiting

Active in production via `RateLimitMiddleware` (see `api/middleware/rate_limit.py`).

| Bucket | Limit | Endpoint pattern |
| --- | --- | --- |
| `trade_write` | 20/min | POST /trades/confirm, /close, /skip |
| `take` | 10/min | POST /trades/take, /signals/take |
| `risk_calc` | 30/min | POST /risk/calculate |
| `config_write` | 5/min | POST/PUT/DELETE /config/profiles |
| `ea_control` | 3/min | POST /ea/restart, /ea/safe-mode |
| `ws_connect` | 10/min | WS upgrade requests |
| `http` (global) | 140/min (120 + 20 burst) | all other endpoints |

All 429 responses include `Retry-After: 60` header.

Set `RATE_LIMIT_BACKEND=redis` for multi-instance deployments (shared counter).
Production Redis must use AUTH + TLS (`rediss://`).

---

## Other backend WebSocket channels (not used by the selected viewer)

| Path | Description |
| --- | --- |
| `/ws/prices` | Real-time bid/ask per pair |
| `/ws/trades` | Trade lifecycle events |
| `/ws/candles` | OHLC candle updates (M1/M5/M15/H1) |
| `/ws/risk` | Drawdown / equity updates |
| `/ws/equity` | Equity curve points |
| `/ws/alerts` | System alert feed |

These backend channels have their own authentication contract. They are not exposed by the selected viewer proxy, and the viewer does not receive a JavaScript token for them.

---

## Observability

- **Prometheus metrics**: GET `/metrics` (requires auth)
- **Key pipeline metrics** (`monitoring/pipeline_metrics.py`):
  - `wolf_ticks_received_total{symbol}`
  - `wolf_ticks_rejected_spike_total{symbol}`
  - `wolf_ticks_rejected_dedup_total{symbol}`
  - `wolf_ws_connections_active`
  - `wolf_redis_stream_lag_seconds{stream}`
  - `wolf_pipeline_latency_ms{stage}`
- **HTTP metrics** (`api/middleware/prometheus_middleware.py`):
  - `wolf_http_requests_total{method,path_template,status_code}`
  - `wolf_http_request_duration_seconds{method,path_template}`

---

## Load Testing

Before going live with real money, run the load tests:

```bash
# k6 — WS concurrent clients + tick burst + reconnect storm
k6 run tests/load/k6_ws_test.js \
  -e BASE_URL=https://api.yourdomain.com \
  -e WS_URL=wss://api.yourdomain.com/ws \
  -e TOKEN=<jwt>

# Locust — tick ingest + WS sustain + reconnect storm
locust -f tests/load/locust_ingest.py \
  --host https://api.yourdomain.com \
  --users 200 --spawn-rate 20 --run-time 60s --headless \
  -e TOKEN=<jwt>
```

**SLOs required before live money:**

| Metric | Target |
| --- | --- |
| WS latency p95 | < 200 ms |
| WS latency p99 | < 500 ms |
| WS dropped connections | < 1% |
| Tick HTTP p95 | < 100 ms |
| WS reconnect success | > 95% |
