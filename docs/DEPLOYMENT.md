# Deployment Topology — TUYUL FX Wolf-15

## Production Architecture

```text
┌─────────────────────────────────────────────────────────────────────┐
│                          USERS / EA                                  │
└───────────────┬─────────────────────────────┬───────────────────────┘
                │                             │
       HTTPS/WSS traffic               MQL5 EA (local MT5)
                │                             │
                ▼                             ▼
┌────────────────────────┐     ┌─────────────────────────────┐
│   Vercel (Next.js)     │     │  Railway — ea-bridge svc    │
│   dashboard/nextjs/    │     │  POST /api/v1/ea/*          │
│                        │     └──────────────┬──────────────┘
│  NEXT_PUBLIC_API_BASE_ │                    │
│  URL=<https://api…>      │                    │
│  NEXT_PUBLIC_WS_BASE_  │                    │
│  URL=wss://api…/ws     │                    │
└──────────┬─────────────┘                    │
           │ REST (Authorization: Bearer JWT)  │
           │ WS  (?token=JWT)                  │
           ▼                                   ▼
┌──────────────────────────────────────────────────────────────┐
│               Railway — API + Engine Service                  │
│               api_server.py  (FastAPI / Uvicorn)              │
│                                                               │
│  Middleware stack (app_factory.py):                           │
│    1. ForwardedHTTPSRedirect                                  │
│    2. SecurityHeaders (CSP, X-Frame-Options)                  │
│    3. CORS  (CORS_ORIGINS env var)                            │
│    4. PrometheusMiddleware                                     │
│    5. RateLimitMiddleware  ← ACTIVE, per-IP sliding window    │
│                                                               │
│  Auth:  api/middleware/auth.py                                │
│    REST  → Authorization: Bearer `JWT`                        │
│    WS    → ?token=`JWT`  (ws_auth.py)                         │
│                                                               │
│  CORS_ORIGINS=<https://dashboard.yourdomain.com>               │
└──────────────────────┬─────────────────────────────────────--┘
                       │
          ┌────────────┴────────────┐
          ▼                         ▼
┌─────────────────┐      ┌─────────────────────┐
│  Railway Redis  │      │  Railway Postgres    │
│  streams/cache  │      │  config / audit /    │
│                 │      │  journal / ledger    │
└─────────────────┘      └─────────────────────┘

```

---

## Services

| Service | Platform | Purpose |
| --- | --- | --- |
| Dashboard | Vercel | Next.js frontend — account governor, ledger, monitoring |
| API + Engine | Railway | FastAPI backend — constitution, risk, execution, WS broker |
| Redis | Railway (managed) | Tick streams, context cache, rate-limit state |
| Postgres | Railway (managed) | Config profiles, journal, account ledger |
| EA bridge | Railway **or** local MT5 host | Receives execution commands from EA, reports fills |

---

## Environment Variables

### Backend (Railway)

```env
# Auth
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
```

### Frontend (Vercel)

```env
NEXT_PUBLIC_API_BASE_URL=https://api.yourdomain.com
NEXT_PUBLIC_WS_BASE_URL=wss://api.yourdomain.com/ws
NEXT_PUBLIC_TIMEZONE=Asia/Singapore
NEXT_PUBLIC_VERDICT_REFRESH_MS=5000
NEXT_PUBLIC_CONTEXT_REFRESH_MS=10000
NEXT_PUBLIC_HEALTH_REFRESH_MS=30000
```

> **Note:** Never use `NEXT_PUBLIC_API_URL` or derive WS URL via
> `replace(/^http/, "ws")`. Always set both `NEXT_PUBLIC_API_BASE_URL`
> and `NEXT_PUBLIC_WS_BASE_URL` explicitly.

---

## Auth Flow

```text
1. User POSTs credentials → POST /api/v1/auth/login
2. Backend issues signed JWT (HMAC-SHA256, DASHBOARD_JWT_SECRET)
3. Frontend stores JWT in localStorage["wolf15_token"]   (lib/auth.ts)
4. Every REST request:  Authorization: Bearer <JWT>      (lib/api.ts, lib/fetcher.ts)
5. Every WS connection: wss://api.domain/ws?token=<JWT>  (lib/websocket.ts)
6. Backend validates JWT via api/middleware/auth.py (same verifier for REST + WS)
```

No cookies. No cross-domain session mismatch. Token expiry is unified.

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

## WebSocket Channels

| Path | Description |
| --- | --- |
| `/ws/prices` | Real-time bid/ask per pair |
| `/ws/trades` | Trade lifecycle events |
| `/ws/candles` | OHLC candle updates (M1/M5/M15/H1) |
| `/ws/risk` | Drawdown / equity updates |
| `/ws/equity` | Equity curve points |
| `/ws/alerts` | System alert feed |

All channels require `?token=<JWT>` query parameter.

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
