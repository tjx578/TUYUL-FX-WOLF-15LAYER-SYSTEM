# Single-owner orchestrator migration specification

## Decision

`wolf15-orchestrator` is the only process allowed to construct and run
`services.orchestrator.state_manager.StateManager`. `wolf15-api` remains an
HTTP/auth/read-model service and reads durable orchestrator state from Redis.

## Source invariants

1. API startup contains no `StateManager` construction, orchestration thread,
   subprocess, lazy route initializer, or fallback runtime.
2. `WOLF15_EMBED_ORCHESTRATOR=true` fails API startup with a clear error.
3. `railway.toml` selects `deploy/railway/start_api.sh`.
4. `railway-orchestrator.toml` selects the standalone entrypoint and is not
   labelled deprecated.
5. API orchestrator endpoints remain read-only projections of durable state.
6. Strategy, risk, ingest, outbox, and EA transport ownership do not move.

## Durable-state and lifecycle contract

The standalone manager consumes account/risk snapshots and publishes state and
heartbeat through the existing Redis keys. Its process owns startup, polling,
compliance evaluation, state publication, heartbeat, shutdown publication, and
its health probe. The API does not own or clean up those tasks.

Singleton protection beyond service topology is a remaining production-hardening
gate; this change removes the known in-process duplicate constructor but does not
claim a distributed lease that the source does not currently implement.

## Verification

`tests/test_orchestrator_runtime_ownership.py` enforces the source and manifest
invariants. Existing orchestrator, route, metric, and Redis integration tests
verify the retained read-model and durable-state behavior.
