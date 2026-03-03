# Railway Production Deployment (Wolf-15)

## Services
1. `wolf-api` → `python api_server.py`
2. `wolf-engine` → `python main.py`
3. `wolf-ingest` → `python ingest_service.py`
4. `wolf-allocation` → `python allocation_worker.py`
5. `wolf-execution` → `python execution_worker.py`
6. (optional) `wolf-risk` → `python risk_state_worker.py`

## Infra
- 1x Redis (event spine)
- 1x Postgres (source of truth)

## Redis Topics
- `context:stream`
- `signals:global`
- `allocation:request`
- `execution:queue`
- `trade:updates`
- `account:updates`

## Non-Negotiable Runtime Guards
- API rejects execution if no Layer-12 verdict ID.
- Allocation must call prop guard before enqueue execution.
- Execution must never alter strategy fields (direction/entry/SL/TP).
- Journal writes are append-only (no update/delete path).