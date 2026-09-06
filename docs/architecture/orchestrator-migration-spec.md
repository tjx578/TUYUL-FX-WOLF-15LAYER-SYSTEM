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

The standalone process uses an atomic Redis lease whose monotonically increasing
generation is included in every state and heartbeat. Lua compare-and-write
scripts bind lease validation and each state, heartbeat, publication, and
kill-switch write into one Redis operation. After expiry/takeover, an older
generation cannot write or release the new owner's lease. Standby instances are
live but not writer-ready.

The runtime supervisor distinguishes `STARTING`, `STANDBY`, `OWNER`, `FATAL`,
and `STOPPED`. Its progress timeout defaults to three compliance intervals with
a 30-second floor and can be set explicitly with
`ORCHESTRATOR_STALL_TIMEOUT_SEC`. Fatal or stagnant evaluators fail liveness;
valid compliance holds such as `ACCOUNT_STATE_MISSING` do not.

## Verification

`tests/test_orchestrator_runtime_ownership.py` enforces the source and manifest
invariants. Existing orchestrator, route, metric, and Redis integration tests
verify the retained read-model and durable-state behavior. Fencing and runtime
truth are covered by `tests/test_orchestrator_fencing.py` and
`tests/test_orchestrator_supervisor.py`.
