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

The API also owns `TradeOutboxWorker` strictly as WebSocket projection delivery.
It consumes `trade:outbox`, broadcasts live-view events, and updates only
projection delivery/retry bookkeeping. It does not claim commands, create
execution intents, or contact MT5/brokers. Each API process uses a distinct
consumer identity; this placement does not grant execution authority.

`WOLF15_EMBED_ORCHESTRATOR=true` is rejected. The API must never construct
`StateManager`, create an orchestration thread, or treat orchestrator health as
execution authority. `/healthz` is liveness; governed readiness is separate.

Failure modes include dependency degradation, router boot errors, and stale
orchestrator heartbeat. Verify with `tests/test_orchestrator_runtime_ownership.py`,
`tests/test_orchestrator_routes.py`, `tests/test_metrics_endpoint.py`, and
`tests/unit/test_trade_outbox_worker.py`.
