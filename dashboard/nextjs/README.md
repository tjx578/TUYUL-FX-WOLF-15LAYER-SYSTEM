# WOLF15 Railway owner dashboard

The supported frontend is the existing service WOLF15-DASHBOARD-FRONTEND:
https://wolf15-dashboard-frontend-production.up.railway.app/login

Its active page renders `src/components/wolf15-v2/RailwayDashboard.js`. The nine
views share one read-only snapshot; the old prototype page routes, local-storage
token login and session-refresh design have been removed.

## Login and data flow

The owner submits username and password to the same-origin `/api/auth/owner-login`.
Only the server contacts the configured core `/api/auth/owner-login`. The browser
receives `{ok:true}` and a Secure, HttpOnly, SameSite=Lax viewer cookie. The API
owns the password verifier and JWT signing secret. The frontend never receives
machine API keys, an owner verifier or a signing secret. Password-issued viewer
sessions expire after at most 900 seconds and cannot use legacy reissuance.

Browser -> Railway frontend -> core API. There is no separate BFF hop, public API
environment variable, direct browser API request or browser WebSocket connection.
The proxy accepts only these exact GET routes, with no query parameters:

| Same-origin projection | Core reads |
| --- | --- |
| `/api/proxy/dashboard/overview` | `/api/v1/status` and `/healthz` |
| `/api/proxy/dashboard/feed-status` | `/api/v1/candles/feed-status` |
| `/api/proxy/dashboard/aggregated-status` | `/api/v1/status` |

The server verifies the viewer JWT and `read:dashboard` scope, then returns an
explicit sanitized schema. Raw error details, credentials, unknown nested data,
upstream cookies, private-origin headers and hardcoded activity placeholders do
not reach the browser. Missing data stays unknown. No trading/control route is
exposed by the frontend.

## Existing Railway service configuration

Use `dashboard/nextjs` as the frontend build root, its Dockerfile, and port 8080,
matching the existing domain target. Server variables are:

```dotenv
DASHBOARD_MODE=viewer
DASHBOARD_CANONICAL_ORIGIN=https://wolf15-dashboard-frontend-production.up.railway.app
INTERNAL_API_URL=https://wolf15-api-production.up.railway.app
PORT=8080
```

The API URL must be a credential-free HTTPS origin distinct from the frontend.
The API browser-origin setting is the exact frontend origin; explicit local
development overrides remain possible. No provider preview origins are inferred.
The API must use the API-only entrypoint without embedded orchestrator activation.

## Local verification

Use Node 22 and `npm ci`. `npm run build:strict` validates the server origins and
builds the standalone frontend with the TypeScript check enabled. `npm run lint`
runs the retained source checks. Set OWNER_LOGIN_TEST_PYTHON to the isolated test
interpreter before `npm test`; its disposable fixture never starts the engine.
For local development, override the browser origin to http://localhost:3000 and
the API to a separate loopback service; production API transport requires HTTPS.

## Release state

These repository changes do not deploy the service. The public login observed
during this revision still displayed VIEWER JWT. The production service has
pending provider configuration changes whose origin/values are not established
by source validation; do not apply unrelated pending changes as part of a release.
Linux image/source attestation, live username/password acceptance and production
network/data checks remain separate gates. A local synthetic login proves only
the tested revision and does not authorize trading or production changes.
