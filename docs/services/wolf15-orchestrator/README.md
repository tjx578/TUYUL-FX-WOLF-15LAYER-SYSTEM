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

Startup hydrates only committed, scoped state and revalidates current inputs;
historical state never inherits freshness or execution authority. Process-local
inflight evaluation must finish or cancel at shutdown, while a completed commit
must not be repeated after restart. The detailed boundaries—including the
intentional process-local semantics of `recovery_count`—are defined in the
[state authority and recovery contract](../../architecture/orchestrator-state-authority-recovery.md).

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

See the [Redis ownership/fencing ADR](../../architecture/adr-redis-orchestrator-ownership-fencing.md)
for why PostgreSQL is not added as a second coordination guard.
