# contracts/

Typed Pydantic contracts that enforce structural validation at service boundaries.

## Purpose

Prevent silent field-missing, type-coercion, and schema-drift bugs when data flows between services through Redis Streams, Pub/Sub, key-value, REST, or WebSocket.

Contracts live here — never in the service that produces or consumes the data. This keeps the schema neutral and auditable.

## Module inventory

| Module | Scope | Key models |
|--------|-------|------------|
| `redis_stream_contracts.py` | Redis inter-service messages | `VerdictPayload`, `ExecutionIntentPayload`, `WorkerResultPayload`, `OrchestratorCommand` |
| `execution_queue_contract.py` | Allocation → execution worker stream | `ExecutionQueuePayload` |
| `websocket_events.py` | Real-time dashboard WS channels | `MarketEvent`, `SignalEvent`, `RiskEvent` |
| `dashboard_dto.py` | Dashboard REST view models | `SignalView`, `RiskRecommendation` |
| `api_response_schema.py` | Generic API envelope | `ApiResponse[T]` |

## Coverage status

### Covered (typed + validated)

- L12 verdict cache → signal_service / allocation (`VerdictPayload`)
- Coordinator → execution stream (`ExecutionIntentPayload`)
- Worker job results → Redis key (`WorkerResultPayload`)
- Orchestrator mode-change pub/sub (`OrchestratorCommand`)
- Allocation → execution worker queue (`ExecutionQueuePayload`)
- Dashboard WS events (`MarketEvent`, `SignalEvent`, `RiskEvent`)

### Outstanding (ad-hoc or untyped)

- `ACCOUNT_STATE` key — orchestrator reads, shape validated inline
- `TRADE_RISK` key — risk engine writes, orchestrator reads
- `HEARTBEAT_*` keys — heartbeat producers, compliance freshness checks
- `NEWS_LOCK:STATE` key — API writes, orchestrator reads
- `PRICE:*` hashes — PriceFeed read model

Priority: `ACCOUNT_STATE` and `TRADE_RISK` should be contracted next since the orchestrator compliance guard depends on their shape.

## Orchestrator guard mappings

The orchestrator `StateManager` (`services/orchestrator/state_manager.py`) consumes several Redis keys and maps them to compliance guard inputs:

| Redis key | Guard input field | Compliance check |
|-----------|-------------------|------------------|
| `ACCOUNT_STATE` | `balance`, `equity`, `drawdown_*` | Account health gates |
| `TRADE_RISK` | `risk_*`, `exposure_*` | Risk limit gates |
| `NEWS_LOCK:STATE` | `news_lock_active` | News event lockout |
| `HEARTBEAT_INGEST` | `data_stale`, `staleness_seconds` | Data freshness gate |
| (runtime) | `session_locked` | Forex market hours gate |

These mappings are computed in `_refresh_compliance_signals()` and evaluated by `evaluate_compliance()`.

## Rules

- Contracts must not contain market logic or execution authority.
- `extra="forbid"` is the default strictness unless a model explicitly documents why `extra="allow"` is needed.
- Adding or removing a field is a breaking change — update all producers and consumers before merging.
- See `docs/architecture/service-contracts.md` for the full cross-service contract reference.
