# Railway Dashboard — Direct Core API Topology

**Status:** Canonical repository contract; production rollout remains HOLD.
**Updated:** 2026-09-09 (dashboard scope only).
**Filename:** `dashboard-hybrid-topology.md` is retained so existing links resolve. Its former hybrid routing prescription is superseded by this direct API contract.

## Selected service and evidence boundary

- Dashboard: `https://wolf15-dashboard-frontend-production.up.railway.app`
- Login: `https://wolf15-dashboard-frontend-production.up.railway.app/login`
- Core API: `https://wolf15-api-production.up.railway.app`
- Selected frontend service port: `8080`, confirmed from provider metadata.
- Source: `dashboard/nextjs/`; Railway Docker/standalone deployment.

These are the selected existing services. The repository revision does not prove a deployment: the observed public login still shows `VIEWER JWT`. Password-login and direct-core production acceptance remain unverified. No production deployment, variable change, credential creation or trading activation is authorized by this document.

## Request path

```text
Browser on selected Railway origin
  -> same-origin Next.js owner-login/session and three GET projections
  -> server-only INTERNAL_API_URL
  -> existing core API auth and read endpoints
```

| Browser request | Core request made by Next server | Browser projection |
| --- | --- | --- |
| POST `/api/auth/owner-login` | POST `/api/auth/owner-login` | Session result; JWT retained in HttpOnly cookie |
| GET `/api/proxy/dashboard/overview` | GET `/api/v1/status` and `/healthz` | Sanitized `{status, health, source}` |
| GET `/api/proxy/dashboard/feed-status` | GET `/api/v1/candles/feed-status` | Sanitized feed metadata and `source` |
| GET `/api/proxy/dashboard/aggregated-status` | GET `/api/v1/status` | Sanitized `{core_status, source}` |
| DELETE `/api/set-session` | No core business request | Clear browser session |

Session validation uses the existing core `/api/auth/session` endpoint. The proxy accepts exactly the three listed GET paths. Unknown paths, extra query parameters and mutations fail before any upstream fetch. There is no general API passthrough, browser WebSocket/SSE route or upstream fallback in this viewer profile.

## Authentication and authority

The owner authenticates with username/password; the backend issues a JWT with `role=viewer` and explicit `read:dashboard`. The Next server sets the `wolf15_session` cookie with HttpOnly, Secure and SameSite protection. Browser JavaScript receives no JWT or machine credential. Session expiry is bounded to 15 minutes; the password-owner subject cannot obtain successor tokens through legacy refresh/session/login routes.

Middleware converts the session cookie to an explicit Bearer header for the server proxy. The proxy validates the session with core and requires JWT authentication, viewer role and the dashboard-read scope. Owner/operator/admin roles and machine API keys cannot authorize this viewer profile. Session cookies are not forwarded as core business credentials.

The dashboard observes existing backend state. It cannot create verdicts, alter strategy, call execution/broker routes, write risk/configuration state or enable engine/orchestrator work. The selected API deployment must remain API-only (`WOLF15_EMBED_ORCHESTRATOR=false`); this repository change does not modify a running API service.

## Server-side projection and failures

`src/lib/server/viewerProjection.ts` selects explicit safe fields before JSON reaches the browser. It excludes raw `detail`, `router_boot_errors`, arbitrary nested payloads, credential fields and hardcoded placeholder activity/MT5 values. Numeric values must be finite and bounded; enum strings, symbol identifiers and collection size are validated. Missing observations remain null/unknown.

Core responses are capped at 128 KiB and feed collections at 256 symbols. Reads use a five-second timeout, reject redirects and use `cache: no-store`. Failed or malformed core responses yield a generic 502; missing/invalid core configuration yields 503. Responses never expose upstream error bodies, cookies or private origin diagnostics.

Browser responses carry `cache-control: no-store`, `x-proxy-surface: core-api` and a server-generated `x-request-id`. There is no BFF cache header or user-shared response cache. Backend liveness is separate from freshness, database availability and trading readiness.

## Repository configuration

```env
DASHBOARD_MODE=viewer
DASHBOARD_CANONICAL_ORIGIN=https://wolf15-dashboard-frontend-production.up.railway.app
INTERNAL_API_URL=https://wolf15-api-production.up.railway.app
PORT=8080
```

`INTERNAL_API_URL` is server-only and must be a credential-free bare HTTPS origin in production. It cannot equal the dashboard origin. Missing or invalid values fail closed. The selected frontend does not require public API/WS variables or a dashboard-BFF variable. Provisioning any production password verifier/signing secret is a separate backend-only operation requiring its own authorization.

## Legacy service boundary

`services/dashboard_bff/` and its standalone deployment artifacts remain legacy Python service code. They are disconnected from the selected frontend and are not a dependency or fallback for its login or read projections. This does not claim that an existing provider BFF service has been stopped or deleted.

## Verification required before promotion

- Exact source/commit identity and preserved dirty-checkout recovery.
- Strict frontend build, owner auth and exact-path containment tests.
- Direct core mapping, server-side secret projection and bounded failure tests.
- Browser password login, expiry, logout and denied privilege checks on the selected production origin.
- API-only effective entrypoint; source-to-image-to-domain identity; TLS/network and actual read-data acceptance.

Local checks and provider metadata do not satisfy the production gates. Keep HOLD until each gate has direct evidence.

Related: [Dashboard authority](dashboard-control-surface.md), [runtime topology](runtime-topology-current.md), [go-live gates](operations/go-live-checklist.md).
