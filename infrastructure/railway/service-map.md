# Wolf-15 Railway Service Map

## Services

| Service | Type | Public | Entrypoint | Responsibility |
| --- | --- | ---: | --- | --- |
| wolf15-api | Web Service | Yes | deploy/railway/start_api.sh | REST, WebSocket, read-only aggregation |
| wolf15-engine | Worker | No | deploy/railway/start_engine.sh | Stream consume, L1-L12 pipeline, signal publish |
| wolf15-ingest | Worker | No | deploy/railway/start_ingest.sh | Finnhub/MT5 ingest, normalize, tick publish |
| wolf15-orchestrator | Worker | No | services/orchestrator | Mode control, compliance guard, kill switch |
| wolf15-worker | Cron/Worker | No | services/worker | Monte Carlo, recalibration, backtest |
| redis | Plugin | Internal | Railway Redis | Event bus + state cache |
| postgres | Plugin | Internal | Railway Postgres | Audit, logs, historical analytics |

## Boundary Rules

1. Layer-12 remains sole decision authority.
2. API is read-only against decision authority.
3. Engine has no public HTTP surface.
4. Ingest never calls engine internals directly.
5. Orchestrator only governs mode/compliance.
