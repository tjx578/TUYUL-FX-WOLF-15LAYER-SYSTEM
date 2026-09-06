# wolf15-orchestrator

**Role:** sole owner of runtime orchestration and compliance evaluation.

- Manifest: [`../../../railway-orchestrator.toml`](../../../railway-orchestrator.toml)
- Start script: [`../../../deploy/railway/start_orchestrator.sh`](../../../deploy/railway/start_orchestrator.sh)
- Runtime module: [`../../../services/orchestrator/state_manager.py`](../../../services/orchestrator/state_manager.py)

The process owns Redis command subscription, durable account/risk snapshot reads,
compliance ticks, orchestrator state and heartbeat publication, shutdown state,
and its health probe. A Redis lease with monotonically increasing generation
fences every state, heartbeat, and kill-switch write. It does not own strategy
analysis, risk sizing, trade-outbox projection delivery, command issuance, EA
transport, or broker execution.

`/healthz` reports supervisor liveness and fails on fatal or stagnant runtime;
`/readyz` is true only for the current lease owner. A healthy standby is live but
not writer-ready. Compliance mode remains separate: missing account state holds
compliance without making the evaluator process unhealthy. Startup and shutdown
are entirely owned by this process.

Ownership configuration is explicit: `ORCHESTRATOR_LEASE_KEY`,
`ORCHESTRATOR_FENCE_COUNTER_KEY`, `ORCHESTRATOR_LEASE_TTL_SEC`,
`ORCHESTRATOR_LEASE_RENEW_INTERVAL_SEC`, and
`ORCHESTRATOR_STALL_TIMEOUT_SEC`. The renewal interval must be less than half
the lease TTL or startup fails closed. Deployment/replica identity is only an
operator-readable prefix; every process appends a unique nonce.

Verify with `tests/test_orchestrator_runtime_ownership.py`,
`tests/test_orchestrator_state_manager.py`, and
`tests/test_orchestrator_fencing.py`, plus
`tests/integration/test_orchestrator_redis_pubsub.py`.
