# wolf15-api

**Role:** HTTP/API facade, authentication, and read models. It is not a runtime
orchestration owner.

- Manifest: [`../../../railway.toml`](../../../railway.toml)
- Start script: [`../../../deploy/railway/start_api.sh`](../../../deploy/railway/start_api.sh)
- ASGI app: [`../../../app.py`](../../../app.py) → `app:app`
- Factory/lifecycle: [`../../../api/app_factory.py`](../../../api/app_factory.py)

The process owns HTTP middleware, routers, websocket/read projections, Redis and
PostgreSQL client lifecycle needed by API requests, and API health/readiness.
Orchestrator routes read state published by the standalone owner; they do not
create a scheduler or writer.

`WOLF15_EMBED_ORCHESTRATOR=true` is rejected. The API must never construct
`StateManager`, create an orchestration thread, or treat orchestrator health as
execution authority. `/healthz` is liveness; governed readiness is separate.

Failure modes include dependency degradation, router boot errors, and stale
orchestrator heartbeat. Verify with `tests/test_orchestrator_runtime_ownership.py`,
`tests/test_orchestrator_routes.py`, and `tests/test_metrics_endpoint.py`.
