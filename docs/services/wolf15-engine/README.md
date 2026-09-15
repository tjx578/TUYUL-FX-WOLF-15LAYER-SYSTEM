# wolf15-engine

**Role:** analysis/constitutional pipeline and pressure producer.

- Manifest: [`../../../railway-engine.toml`](../../../railway-engine.toml)
- Start script: [`../../../deploy/railway/start_engine_consolidated.sh`](../../../deploy/railway/start_engine_consolidated.sh)
- Runtime module: [`../../../services/engine/runner.py`](../../../services/engine/runner.py)

The process owns database schema preflight, engine health probe, analysis-loop
startup, and guarded pressure output. Ingest remains a separate service. The
engine does not own compliance orchestration or broker execution.

`RUN_MODE=engine-only` and Redis context mode are enforced by the start script.
`/healthz` is process liveness; provider/context/verdict readiness is enforced by
internal gates. Execution flags remain independent and fail-closed.

Verify with engine runner/preflight, pressure writer, pipeline, and containment
tests. Migration ownership remains with the migrator service.
