# Wolf-15 Railway Service Map

## Services

| Service | Type | Public | Entrypoint | Responsibility |
| --- | --- | ---: | --- | --- |
| wolf15-api | Web Service | Yes | deploy/railway/start_api.sh | REST, WebSocket, read-only aggregation |
| wolf15-engine | Worker | No | deploy/railway/start_engine.sh | Stream consume, L1-L12 pipeline, signal publish |
| wolf15-ingest | Worker | No | deploy/railway/start_ingest.sh | Finnhub/MT5 ingest, normalize, tick publish |
| wolf15-orchestrator | Worker | No | deploy/railway/start_orchestrator.sh | Mode control, compliance guard, kill switch |
| wolf15-migrator | Worker (one-shot) | No | deploy/railway/start_migrator.sh | Alembic schema migration actor |
| wolf15-worker-montecarlo | Cron/Worker (one-shot) | No | deploy/railway/start_worker.sh services.worker.montecarlo_job | Monte Carlo simulation job |
| wolf15-worker-backtest | Cron/Worker (one-shot) | No | deploy/railway/start_worker.sh services.worker.nightly_backtest | Nightly backtest job |
| wolf15-worker-regime | Cron/Worker (one-shot) | No | deploy/railway/start_worker.sh services.worker.regime_recalibration | Regime recalibration job |
| redis | Plugin | Internal | Railway Redis | Event bus + state cache |
| postgres | Plugin | Internal | Railway Postgres | Audit, logs, historical analytics |

## Boundary Rules

1. Layer-12 remains sole decision authority.
2. API is read-only against decision authority.
3. Engine has no public HTTP surface.
4. Ingest never calls engine internals directly.
5. Orchestrator only governs mode/compliance.
