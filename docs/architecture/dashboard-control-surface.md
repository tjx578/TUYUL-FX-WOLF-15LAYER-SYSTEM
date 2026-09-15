# Dashboard Viewer Authority

**Status:** Canonical repository contract for the selected Railway dashboard.
**Updated:** 2026-09-13 (dashboard scope only).

The selected owner interface is `https://wolf15-dashboard-frontend-production.up.railway.app/login`. Its frontend serves on port `8080` and calls `https://wolf15-api-production.up.railway.app` through same-origin Next server handlers. The public login observed during this revision still shows `VIEWER JWT`; the password-login revision is repository work and production acceptance remains HOLD.

## Allowed operations

The owner may authenticate with username/password, read sanitized system/feed/pair projections, refresh those observations and log out. The authenticated session is deliberately `role=viewer` with `read:dashboard`, not an administrative or execution role.

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

Only GET `/api/proxy/dashboard/overview`, `/api/proxy/dashboard/feed-status`, `/api/proxy/dashboard/aggregated-status` and `/api/proxy/dashboard/pair-states` are exposed. The Next server maps them to existing core read endpoints, filters response fields before browser delivery and fails closed on unknown paths, query parameters, mutations or upstream errors. There is no BFF dependency, general API fallback, browser WebSocket or SSE channel.

`INTERNAL_API_URL` is a server-only HTTPS origin. `DASHBOARD_CANONICAL_ORIGIN` binds browser login/logout to the selected Railway origin. Neither origin is a credential or evidence that the candidate is deployed.

See [the direct API topology contract](dashboard-hybrid-topology.md) for exact paths, schemas, timeout/body limits and deployment gates. Its historical filename is retained for link compatibility.

## Health and evidence

Core `/healthz` and `/health` describe process liveness. Core readiness, deep diagnostics, data freshness, database identity and broker execution evidence remain distinct. The selected viewer receives sanitized status/feed fields; it does not expose raw diagnostic exceptions, private origins or arbitrary backend payloads.

`dashboard/pair-states` reads core `GET /api/v1/verdict/all` and projects, per pair, only the symbol, the constitutional verdict, the governance admission action and a quality state derived from the snapshot age. The verdict whitelist is the core contract for that endpoint — `EXECUTE`, `EXECUTE_BUY`, `EXECUTE_SELL`, `NO_TRADE`, `HOLD`, `ABORT` — plus `EXECUTE_REDUCED_RISK_BUY` and `EXECUTE_REDUCED_RISK_SELL`, which `constitution/verdict_engine.py` emits on a near pass or a governance downgrade and which the endpoint returns verbatim even though the contract test does not list them. The admission whitelist is exactly `GovernanceAction`. Confidence, direction, gates, scores, execution maps, diagnostics and error strings are dropped before browser delivery; an unrecognized value is reported as `null`, never passed through. The pair snapshot carries one entry per cached verdict — at most one per configured pair, and fewer during warmup, after cache expiry or wherever a pair has no verdict yet — so it reads under a wider body limit than the scalar status reads while remaining bounded and streamed. Reading pair state is observation only: it does not make the viewer an originator of verdicts, and Layer 12 authority is unchanged.

Domain normalization belongs to the backend. Where the verdict snapshot carries no authoritative governance action, admission stays NOT_MEASURED; the viewer never reproduces the core's normalization to infer one, and never derives an active-lifecycle count from cached verdict snapshots.

Core `GET /api/v1/dashboard/pair-states` is that settled contract. It composes the per-pair projection on the service side — `symbol`, `verdict`, `admission`, `reason_code`, `age_seconds`, `quality`, `warmup_ready`, `active`, `snapshot_present` — applying the shared verdict normalization in `api/verdict_normalization.py` rather than leaving a client to infer an absent governance action. Only declared values are published: a verdict, admission or reason outside its set is `null`, and no confidence, score, gate, execution or diagnostic field is included. `admission` requires affirmative evidence — a declared action on the record, or a recognized governance reason — so a degraded HOLD written after a pipeline timeout, which carries neither, reports `null` rather than a positive admission. A snapshot stamped in the future, or with a non-finite time, has unverifiable freshness and reports `null` age and quality instead of counting as live.

Its response is the **configured pair inventory**: one row per configured pair, with `count` the number of inventory rows published — not a count of cached verdicts. A pair keeps its row when it has no verdict yet, so an operator can distinguish configured-but-not-ready from not-configured: `snapshot_present: false` is a configured pair with no cached verdict, `warmup_ready: false` a configured pair still warming up, and `active: false` a configured pair that is disabled. `source_ok` is taken from the read-health each reader already tracks rather than from exceptions, because both readers are fail-soft: a Redis failure degrades to a missing verdict and zero warmup bars, which would otherwise be indistinguishable from ordinary warmup. Failure counters are captured before health sampling, so concurrent failures cannot be absorbed into the scan baseline. Verdicts use one MGET and warmup counts one pipelined LLEN batch for the configured inventory; no per-pair ping is added. Warmup uses the same canonical minimum counts as the pipeline (including H1=30). The endpoint is authenticated like its read-only siblings in `api/dashboard_routes.py` and carries no write path.

The viewer does not read it yet: `dashboard/pair-states` still projects `GET /api/v1/verdict/all` in the Next server, so admission remains NOT_MEASURED in the browser until that read is moved over. Moving it is what retires the wider body limit this projection needs today.

Unsupported account/risk/execution/audit projections remain NOT_MEASURED. A reachable page, a healthy process or successful local test does not prove production login, data freshness or trading readiness.

## Separate legacy machine-key policy

Legacy `dashboard/api_key_manager.py` remains backend machinery outside this viewer flow. Its ACTIVE, bounded ROTATING-grace and REVOKED states do not grant browser authority. Keys and rotation operations remain machine-only. The legacy standalone Python BFF is disconnected from this frontend; its presence in the repository is not a current routing prescription.

## Release boundary

This revision changes repository files only. Deployment, provider-variable updates, secret provisioning, database/broker operations and trading activation require separately authorized work. Keep production HOLD until exact-source build, containment, secret scan and selected-origin login/data acceptance have evidence.
