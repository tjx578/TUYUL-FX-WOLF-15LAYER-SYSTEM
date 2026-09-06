# Railway service ownership index

These documents describe the seven core Railway application services in the
current repository tree. They are source contracts, not evidence that production
has been deployed. Exact commit/tree identity belongs in the external release
attestation so this tracked document does not create a self-referential hash.

| Service | Canonical documentation | Runtime entrypoint |
| --- | --- | --- |
| `wolf15-api` | [API](wolf15-api/README.md) | `deploy/railway/start_api.sh` |
| `wolf15-orchestrator` | [Orchestrator](wolf15-orchestrator/README.md) | `deploy/railway/start_orchestrator.sh` |
| `wolf15-ingest` | [Ingest](wolf15-ingest/README.md) | `deploy/railway/start_ingest.sh` |
| `wolf15-engine` | [Engine](wolf15-engine/README.md) | `deploy/railway/start_engine_consolidated.sh` |
| `wolf15-pressure-outbox` | [Pressure outbox](wolf15-pressure-outbox/README.md) | `deploy/railway/start_pressure_outbox.sh` |
| `wolf15-execution` | [Trade/execution](wolf15-execution/README.md) | `deploy/railway/start_trade_consolidated.sh` |
| `wolf15-ea-bridge` | [EA bridge](wolf15-ea-bridge/README.md) | `deploy/railway/start_ea_bridge.sh` |

Machine-readable bindings are in [runtime-ownership-map.json](runtime-ownership-map.json).
The seven additional package domains are explicitly reconciled in
[Additional domain dispositions](additional-domain-dispositions.md). Historical
worker or infrastructure names are not promoted to always-on application
services without current manifest and entrypoint evidence.

Architecture decisions and acceptance tracking:

- [Redis orchestrator ownership/fencing ADR](../architecture/adr-redis-orchestrator-ownership-fencing.md)
- [State authority and recovery contract](../architecture/orchestrator-state-authority-recovery.md)
- [T01-T15 and R01-R08 traceability](../architecture/orchestrator-acceptance-traceability.md)
