# Copilot Coding Agent Instructions — TUYUL FX / Wolf-15 Layer System

## Non-Negotiable Rules (Constitutional)
1. **Never add execution authority to analysis or reflective modules.**
2. **Never allow dashboard or EA to override Layer-12 verdict.**
3. **Never compute market direction in execution/dashboard.**
4. **Journal is write-only / append-only (immutable).** See `journal/audit_trail.py` (hash-chained entries).
5. **EA is an executor only.** All state/risk comes from dashboard.
6. **L12 signals must NOT contain account state** (`balance`, `equity`, `margin`). `schemas/signal_validator.py` enforces this check.

If a request conflicts with these, propose an alternative design that preserves authority boundaries.

---

## Architecture — Authority Zones

| Zone | Directory | Authority | Key files |
|------|-----------|-----------|-----------|
| Analysis | `analysis/`, `analysis/layers/` | Read-only metrics (L1–L11). No side-effects. | `analysis/layers/l1_context.py` … `l11_rr.py` |
| Constitution | `constitution/` | **Sole decision gate (L12).** | `constitution/gatekeeper.py` (9-gate sequential), `constitution/verdict_engine.py` (V1/V2) |
| Execution | `execution/` | Blind order placement. No strategy logic. | `execution/state_machine.py` (Enum FSM: IDLE→PENDING_ACTIVE→FILLED/CANCELLED) |
| Dashboard | `dashboard/` | Account governor + ledger + monitoring. | `dashboard/backend/`, `dashboard/nextjs/` (Next.js App Router) |
| Risk | `risk/`, `accounts/` | Prop firm guards + account limits. | `risk/prop_firm.py` — `check(account_state, trade_risk) → {allowed, code, severity}` |
| Journal | `journal/` | Immutable audit (J1–J4). No decision power. | `journal/journal_writer.py` (append-only), `journal/audit_trail.py` (hash-chained JSONL + Postgres) |

**Pipeline orchestrator**: `analysis/orchestrators/unified_pipeline.py` (~1600 lines) runs all 15 layers in 8 phases. This is the primary analytical entrypoint — not `main.py`.

---

## Service Topology (Multi-service on Railway)

Each service has its own `railway-*.toml`. All share one `Dockerfile` (multi-stage, Python 3.11).

| Service | Entrypoint | Port |
|---------|-----------|------|
| **API** | `app.py` → `api/app_factory.py` (FastAPI + gunicorn/uvicorn) | 8080 |
| **Engine** | `services/engine/runner.py` → `main.py` | 8081 |
| **Ingest** | `services/ingest/ingest_worker.py` → `ingest_service.py` (Finnhub WS/REST) | 8082 |
| **Orchestrator** | `services/orchestrator/` | — |
| **Workers** | `services/worker/` (cron-scheduled: backtest, montecarlo, regime) | — |

Workers select module via `WOLF15_WORKER_ENTRY` env var. Ingest uses `CONTEXT_MODE` env var for Redis vs Finnhub candle seeding.

---

## Inter-Service Communication

- **Redis Streams** (`XADD`/`XREADGROUP` with `XACK` + PEL recovery) — All critical data: ticks, candles, signals, trades. See `infrastructure/redis/stream_publisher.py`, `stream_consumer.py`. Three priority tiers (CRITICAL/NORMAL/LOW).
- **Redis Pub/Sub** — Ephemeral only (heartbeats, cache invalidation). **Messages lost during disconnect** — never use for critical data. See `infrastructure/redis/pubsub_manager.py`.
- **In-process EventBus** — `infrastructure/event_bus.py` — typed events within a single service process.
- **HTTP REST** — EA/external → API service. Auth via `api/middleware/auth_middleware.py`.
- **Key registry**: `state/redis_keys.py`, `state/channels.py`, `state/consumer_groups.py`.

---

## Developer Workflows

### Tests
```
pytest                           # full suite (~150+ test files, 30s timeout per test)
pytest tests/test_l12_gate.py    # single file
pytest -m "not slow"             # skip slow tests
pytest -m integration            # integration only
```
- Config: `pytest.ini` (`asyncio_mode = auto`, `--strict-markers`). Markers: `slow`, `integration`, `ws`, `concurrent`.
- Coverage minimum: **85%** (enforced in `pyproject.toml` over `analysis/constitution/execution/dashboard/journal/risk`).
- Root `conftest.py` provides: `sample_l12_verdict`, `sample_l12_reject`, `sample_account_state`, `sample_trade_risk`, `ftmo_profile`, `mock_db`.
- **Architectural boundary tests** exist (e.g., `tests/test_signal_integrity.py`) that scan source files to enforce no cross-imports between zones.

### Linting & Type Checking
- **Ruff**: `ruff check .` / `ruff format .` — Config in `pyproject.toml`. Line length 120, Python 3.11 target. `E501` ignored.
- **Pyright**: `pyrightconfig.json` — Strict mode. `extraPaths: [".", "./services/api"]`.
- **Mypy**: `pyproject.toml` — `disallow_untyped_defs = true` (relaxed for `tests/`, `scripts/`).

### Database Migrations
- **Alembic** with PostgreSQL (`asyncpg`/`psycopg`). Config in `alembic.ini`.

---

## Code Patterns & Conventions

### Analysis Layers (`analysis/layers/l*.py`)
- Class-based with `analyze(candles, ...)` method. Pure functions, no side effects.
- Zone annotation in docstring: `"Zone: analysis/ -- pure read-only analysis, no execution side-effects."`
- Use `__all__` exports. Optional enrichment via try/except import for engines that may not be available.

### API Routers (`api/`)
- Routers registered via `api/router_registry.py` — single declarative list of `RouterEntry` dataclasses. Factory (`api/app_factory.py`) dynamically imports and mounts them.
- Pattern: `router = APIRouter(prefix="/api/v1/<domain>", tags=[...])`. Auth via `verify_api_key` dependency. Write endpoints add `enforce_write_governance`.
- Pydantic models for request/response validation. Redis keys as module-level constants.

### State Machine (`execution/state_machine.py`)
- Enum-based FSM. **Singleton** (thread-safe via `threading.Lock`). Static transition table.
- Replay-safe: terminal→same-terminal returns `REPLAY_TERMINAL_NOOP` instead of raising.
- States: `IDLE`, `PENDING_ACTIVE`, `FILLED`, `CANCELLED`. Events: `PLACE_ORDER`, `ORDER_FILLED`, `ORDER_CANCELLED`, `ORDER_EXPIRED`.

### Config Loading (`config_loader.py`)
- Module-level singleton dict `CONFIG` loaded at import time from YAML files in `config/`. No runtime reload.
- Access via `get_setting(key)`, `get_pairs()`, `get_prop_firm_config()`, etc.

### Verdict Values
- `EXECUTE`, `EXECUTE_REDUCED_RISK`, `HOLD`, `NO_TRADE`, `ABORT`.
- Score thresholds: wolf ≥ 0.70, tii ≥ 0.90, frpc ≥ 0.93 (see `VerdictThresholds` dataclass in `constitution/verdict_engine.py`).

### Contracts (`contracts/`)
- `ServiceEnvelope` — generic Pydantic wrapper (correlation_id, payload, timestamp).
- `WSMessage` / `WSBroadcast` — WebSocket event contracts with `event_type` discriminators.

### Two Redis clients coexist
- Async: `infrastructure/redis/redis_client.py` (used by infrastructure and pipeline).
- Sync: `dashboard/backend/` and `ea_interface/` use sync Redis for logging/bridge.

---

## Data Contracts (Key Schemas)

### L12 Signal (`schemas/l12_schema.json`, `schemas/signal_contract.py`)
- Required: `symbol`, `verdict`, `confidence`. Must NOT contain account-level fields.
- Signal contract (`SignalContract`): immutable, versioned, includes `signal_id`, `direction`, `entry_price`, `stop_loss`, `take_profit_1`, `risk_reward_ratio`, `scores`, `expires_at`.

### Risk Recommendation (Dashboard → EA)
- `trade_allowed`, `recommended_lot`, `max_safe_lot`, `reason`, `expiry`.

### Trade Events (EA → Dashboard)
- Events: `ORDER_PLACED`, `ORDER_FILLED`, `ORDER_CANCELLED`, `ORDER_EXPIRED`, `SYSTEM_VIOLATION`.
- Schema: `schemas/alert_schema.json`.

---

## Security
- Never commit `.env`. Use `.env.example` as template.
- Never print API keys, JWT secrets, Redis passwords.
- Auth: `PyJWT` for tokens, API key middleware for service-to-service.

---

## Definition of Done
- Respects constitutional authority boundaries.
- Includes tests (boundary tests for gates/guards, parametrized for edge cases).
- Updates relevant schemas in `schemas/` if contracts change.
- Does not break `pytest` or `ruff check`.
