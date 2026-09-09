# Dashboard Viewer Authority

**Status:** Canonical repository contract for the selected Railway dashboard.
**Updated:** 2026-09-09 (dashboard scope only).

The selected owner interface is `https://wolf15-dashboard-frontend-production.up.railway.app/login`. Its frontend serves on port `8080` and calls `https://wolf15-api-production.up.railway.app` through same-origin Next server handlers. The public login observed during this revision still shows `VIEWER JWT`; the password-login revision is repository work and production acceptance remains HOLD.

## Allowed operations

The owner may authenticate with username/password, read sanitized system/feed projections, refresh those observations and log out. The authenticated session is deliberately `role=viewer` with `read:dashboard`, not an administrative or execution role.

The selected dashboard cannot synthesize market verdicts, override Layer 12, invoke broker/execution routes, take/close trades, change risk/configuration state or manage engine/orchestrator runtime. Those backend authorities remain separate and are not enabled by owner login.

## Authentication contract

- `DASHBOARD_MODE=viewer` is required.
- Backend password verification issues only the bounded viewer JWT.
- The Next server holds the JWT in a Secure, HttpOnly, SameSite session cookie; browser JavaScript and storage receive no JWT, signing secret or machine credential.
- Server-side core validation requires JWT auth, exact viewer role and explicit `read:dashboard` scope.
- Machine API keys and owner/operator/admin roles cannot substitute for the viewer session.
- The password-owner session expires after at most 15 minutes and cannot use legacy token reissuance endpoints to extend access.
- The selected API must be API-only; `WOLF15_EMBED_ORCHESTRATOR` must remain false before any authorized rollout.

## Direct core read boundary

Only GET `/api/proxy/dashboard/overview`, `/api/proxy/dashboard/feed-status` and `/api/proxy/dashboard/aggregated-status` are exposed. The Next server maps them to existing core read endpoints, filters response fields before browser delivery and fails closed on unknown paths, query parameters, mutations or upstream errors. There is no BFF dependency, general API fallback, browser WebSocket or SSE channel.

`INTERNAL_API_URL` is a server-only HTTPS origin. `DASHBOARD_CANONICAL_ORIGIN` binds browser login/logout to the selected Railway origin. Neither origin is a credential or evidence that the candidate is deployed.

See [the direct API topology contract](dashboard-hybrid-topology.md) for exact paths, schemas, timeout/body limits and deployment gates. Its historical filename is retained for link compatibility.

## Health and evidence

Core `/healthz` and `/health` describe process liveness. Core readiness, deep diagnostics, data freshness, database identity and broker execution evidence remain distinct. The selected viewer receives sanitized status/feed fields; it does not expose raw diagnostic exceptions, private origins or arbitrary backend payloads.

Unsupported account/risk/execution/audit projections remain NOT_MEASURED. A reachable page, a healthy process or successful local test does not prove production login, data freshness or trading readiness.

## Separate legacy machine-key policy

Legacy `dashboard/api_key_manager.py` remains backend machinery outside this viewer flow. Its ACTIVE, bounded ROTATING-grace and REVOKED states do not grant browser authority. Keys and rotation operations remain machine-only. The legacy standalone Python BFF is disconnected from this frontend; its presence in the repository is not a current routing prescription.

## Release boundary

This revision changes repository files only. Deployment, provider-variable updates, secret provisioning, database/broker operations and trading activation require separately authorized work. Keep production HOLD until exact-source build, containment, secret scan and selected-origin login/data acceptance have evidence.
