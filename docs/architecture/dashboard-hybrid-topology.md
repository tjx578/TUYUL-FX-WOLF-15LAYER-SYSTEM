# Dashboard Hybrid Topology

**Status:** Canonical
**Scope:** Optional hybrid BFF routing rules, safety contract, and deployment boundaries.

## Purpose

This document defines the contract for operating a hybrid dashboard
topology where an optional backend-for-frontend (BFF) service runs
alongside the core-api.

The BFF is designed for dashboard-specific workloads: aggregation,
caching, pre-processing, and presentation-layer APIs that do not
belong in the constitutional pipeline.

## Routing Matrix

| Path Pattern | Phase 1 Upstream | Auth | Notes |
| --- | --- | --- | --- |
| `/api/proxy/dashboard/*` | BFF (if deployed) | session → JWT | Allowlisted BFF paths |
| `/api/proxy/bff/*` | BFF (if deployed) | session → JWT | Allowlisted BFF paths |
| `/api/proxy/*` (all other) | core-api | session → JWT | Default upstream |
| `/api/status` | core-api | session → JWT | Operator diagnostics |
| `/api/set-session` | Next.js internal | cookie | Not proxied |
| `/api/auth/ws-ticket` | Next.js internal | cookie | Not proxied |
| WebSocket channels | core-api (direct) | ws-ticket | Phase 1: no BFF WS relay |
| `/healthz`, `/readyz` | core-api | none / machine-key | Infra probes |

### Resolution Logic

Routing is resolved at request time by `resolveDashboardUpstream()` in
`dashboard/nextjs/src/lib/server/dashboardTopology.ts`.

The resolver checks:

1. Is `INTERNAL_DASHBOARD_BFF_URL` set and non-empty?
2. Does the request path match `BFF_ALLOWLISTED_PATHS`?
3. If both: route to BFF. Otherwise: route to core-api.

If the BFF URL is not configured, all traffic routes to core-api.
The allowlist is a static, code-defined set — not configurable via env.

## WebSocket Rule

In Phase 1, all WebSocket channels remain direct-to-backend.

- `NEXT_PUBLIC_WS_BASE_URL` points to core-api
- The multiplexer connects to core-api only
- No WS traffic flows through the BFF

Future phases may introduce WS relay through the BFF, but this requires
multiplexer refactoring to support split-origin connections.

## Auth Rule

The BFF must accept the same auth contract as core-api for proxied
requests:

- `Authorization: Bearer <jwt>` header injected by Next.js middleware
- The BFF must validate the JWT or forward it to core-api for validation
- The BFF must not introduce new auth surfaces for browser traffic
- Machine-to-machine auth between BFF and core-api (if needed) uses
  a separate service key, never the owner session JWT

## Observability Contract

Proxy and status route handlers add surface headers for debugging:

| Header | Value | Route |
| --- | --- | --- |
| `x-proxy-surface` | `core-api` or `bff` | `/api/proxy/[...path]` |
| `x-status-surface` | `core-api` or `bff` | `/api/status` |
| `x-proxy-target` | upstream URL | `/api/proxy/[...path]` (existing) |
| `x-proxy-status` | HTTP status code | `/api/proxy/[...path]` (existing) |

These headers are informational and must not be used for routing decisions.

## Safety Rules

### No silent fallback

If a path is BFF-allowlisted and the BFF is unreachable, the proxy must
return an error. It must NOT silently fall back to core-api. This
prevents phantom routing drift where the dashboard unknowingly consumes
core-api data instead of BFF-processed data.

### No authority escalation

The BFF must not:

- produce constitutional verdicts
- override Layer 12 decisions
- bypass risk firewall or execution boundaries
- mutate trade state
- act as an alternate strategy or analysis engine

### No account state in signals

The BFF must not inject account state (`balance`, `equity`, `margin`)
into Layer 12 signals. Sizing remains the responsibility of the
dashboard/risk zone.

### Allowlist is code-defined

The BFF path allowlist is defined in source code, not in environment
variables. This ensures routing changes require code review and cannot
be silently changed via deployment config.

## Deployment

### Environment Variables

| Variable | Where | Purpose |
| --- | --- | --- |
| `INTERNAL_DASHBOARD_BFF_URL` | Vercel (dashboard) | BFF upstream URL for server-side proxy |
| `INTERNAL_API_URL` | Vercel (dashboard) | Core-api upstream URL (existing) |
| `NEXT_PUBLIC_WS_BASE_URL` | Vercel (dashboard) | WS origin for browser (existing, stays core-api) |

### Railway Service

When deployed on Railway, the BFF runs as a separate service:

- Service name: `wolf15-dashboard-bff`
- Exposes its own `/healthz` and `/readyz`
- Health must not be conflated with core-api health
- Requires access to Redis and/or core-api for data sourcing

### Vercel Configuration

No Vercel config changes are needed. The Next.js proxy reads
`INTERNAL_DASHBOARD_BFF_URL` at request time. If the variable is unset,
all traffic routes to core-api — the system operates in single-upstream
mode identical to the pre-hybrid state.

## Phasing

### Phase 1 (Current)

- REST-only BFF routing via allowlist
- WS remains direct-to-backend
- No circuit breaker (BFF failure = error, not fallback)
- Single BFF instance, no load balancing

### Phase 2 (Future)

- Circuit breaker with configurable thresholds
- WS relay through BFF (requires multiplexer refactoring)
- BFF health monitoring in dashboard diagnostics
- Optional BFF-side caching with TTL policy

## Related Documents

- `docs/architecture/dashboard-control-surface.md` — Dashboard authority boundary
- `docs/architecture/runtime-topology-current.md` — Runtime service topology
