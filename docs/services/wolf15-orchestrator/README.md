# wolf15-orchestrator

**Role:** sole owner of runtime orchestration and compliance evaluation.

- Manifest: [`../../../railway-orchestrator.toml`](../../../railway-orchestrator.toml)
- Start script: [`../../../deploy/railway/start_orchestrator.sh`](../../../deploy/railway/start_orchestrator.sh)
- Runtime module: [`../../../services/orchestrator/state_manager.py`](../../../services/orchestrator/state_manager.py)

The process owns Redis command subscription, durable account/risk snapshot reads,
compliance ticks, orchestrator state and heartbeat publication, shutdown state,
and its health probe. It does not own strategy analysis, risk sizing, command
issuance, EA transport, or broker execution.

`/healthz` reports process liveness/readiness through the shared probe; compliance
mode remains a separate state. Missing account state must remain fail-closed.
Startup and shutdown are entirely owned by this process.

Verify with `tests/test_orchestrator_runtime_ownership.py`,
`tests/test_orchestrator_state_manager.py`, and
`tests/integration/test_orchestrator_redis_pubsub.py`.
