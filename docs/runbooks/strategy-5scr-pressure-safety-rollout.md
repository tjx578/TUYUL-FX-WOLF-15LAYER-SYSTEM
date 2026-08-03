# Strategy 5S-CR pressure safety rollout

Status: operational release gate  
Scope: Pair Admission, material-context identity, Lifecycle V2, pressure radar/outbox, and closed-candle evidence  
Execution boundary: `WAIT`; no risk reservation, command delivery, or `OrderSend`

## Non-negotiable invariants

- Clean-block and watch IDs are lineage only. They cannot grant pair admission or become an execution-grade campaign anchor.
- `pair_eligible_for_analysis=true` requires a canonical `PairAdmissionGrant` from one deployment's global raw ledger, with duration at least 300 seconds and at least three effective ticks.
- Durable pressure writes require the atomic radar path and a valid `ANALYSIS_READY` radar-selection proof. The direct writer is forbidden.
- Material strategy identity excludes `cluster_id`, producer stage, replica, deployment, and status churn.
- `PRICE_FROZEN`, stale D1 context, direction reversal, expired admission, or missing closed-candle evidence fail closed.
- Every pressure/outbox/evidence artifact remains `final_direction=WAIT` and `valid_for_execution=false`.
- All execution-plane flags remain false throughout this runbook.

## Phase 0 — dark code deployment

Deploy the migrator, pressure worker, engine, and API code with no pressure persistence enabled.

Engine variables:

```text
SIGNAL_PRESSURE_OUTBOX_ENABLED=false
SIGNAL_PRESSURE_OUTBOX_WRITE_ENABLED=false
SIGNAL_PRESSURE_RADAR_WRITE_ENABLED=false
SIGNAL_PRESSURE_STATE_JSON_ENABLED=true
```

Pressure-worker variables:

```text
PRESSURE_OUTBOX_EXPECTED_PHASE=dark
SIGNAL_PRESSURE_OUTBOX_ENABLED=false
SIGNAL_PRESSURE_OUTBOX_WRITE_ENABLED=false
SIGNAL_PRESSURE_OUTBOX_DISPATCH_ENABLED=false
STRATEGY_5SCR_PRESSURE_CONSUMER_ENABLED=false
STRATEGY_5SCR_LIFECYCLE_V2_ENABLED=false
STRATEGY_5SCR_LIFECYCLE_V2_SHADOW_ONLY=true
STRATEGY_5SCR_LIFECYCLE_V2_DUAL_WRITE_ENABLED=false
STRATEGY_5SCR_EVIDENCE_ENABLED=false
STRATEGY_5SCR_EVIDENCE_LIVE_ALLOWED=false
STRATEGY_5SCR_OUTCOME_ENABLED=false
```

Execution isolation on every service:

```text
STRATEGY_5SCR_EXECUTION_ENABLED=false
RISK_RESERVATION_ENABLED=false
TRADE_OUTBOX_WRITE_ENABLED=false
EA_COMMAND_DELIVERY_ENABLED=false
MT5_ORDER_SEND_ENABLED=false
```

Required checks:

- pressure worker preflight reports `expected_phase=dark`, `ready=true`, and `execution_isolated=true`;
- engine starts without a partial pressure-writer flag error;
- no pressure outbox row is inserted or claimed;
- normal pressure telemetry is `INFO`; only safety anomalies are `WARNING`.

## Phase 1 — Pair Admission and material-context shadow

Keep all Phase 0 persistence flags off. Observe `SignalPressureStateJSON` only.

Compare by deployment and symbol:

- `pair_admission_monitoring.evaluated_blocks`, `granted_blocks`, `rejected_blocks`, and `grant_rate`;
- `pair_admission_rejection_reason` and `pair_admission_monitoring.rejection_counts`;
- `material_context_hash` and `context_epoch_id` across changes to `cluster_id` and `source_stage`;
- D1 `missed_expected_closed_bars` and freshness basis;
- `quote_health_status`, especially `PRICE_FROZEN` during an open forex session.

Release gate:

- zero clean-block-only admissions;
- zero mixed-deployment admissions;
- cluster/stage churn does not change `material_context_hash`;
- genuine HTF structure changes do change `material_context_hash`;
- weekend closure never produces `PRICE_FROZEN`.

## Phase 2 — Lifecycle V2 shadow validation

Before live outbox rows exist, validate Lifecycle V2 through deterministic replay. Once published pressure rows exist in later phases, the same observer can run in the worker.

```text
STRATEGY_5SCR_LIFECYCLE_V2_ENABLED=true
STRATEGY_5SCR_LIFECYCLE_V2_SHADOW_ONLY=true
STRATEGY_5SCR_LIFECYCLE_V2_DUAL_WRITE_ENABLED=false
STRATEGY_5SCR_LIFECYCLE_V2_METRICS_ENABLED=true
```

Monitor `[Strategy5SCRLifecycleV2Shadow]`:

- `lifecycle_split_reasons`;
- `material_context_transition_count`;
- `transport_identity_churn_ignored_count`;
- `duplicate_event_count`;
- `event_to_lifecycle_compression_ratio`.

Do not enable dual-write until replay/live shadow parity is accepted. `SHADOW_ONLY=false` is rejected by preflight.

## Phase 3 — atomic radar capture on one engine replica

First run the migrator and confirm pressure-outbox, radar, candle, outcome, and Lifecycle V2 schema preflight. Keep the pressure worker dark so rows cannot be claimed.

On exactly one engine replica:

```text
SIGNAL_PRESSURE_OUTBOX_ENABLED=true
SIGNAL_PRESSURE_OUTBOX_WRITE_ENABLED=true
SIGNAL_PRESSURE_RADAR_WRITE_ENABLED=true
```

The engine preflight rejects any partial combination and rejects master+write without radar. Other engine replicas keep all three flags false.

Acceptance checks:

- provisional qualification alone creates no outbox row;
- clean-block lineage alone remains waiting for Pair Admission;
- `ANALYSIS_READY` and outbox enqueue commit atomically;
- every stored `lifecycle_id` equals the canonical `pair_admission_id`;
- duplicate delivery does not advance lifecycle sequence.

Rollback: set the three engine flags to false. Pending durable rows remain untouched.

## Phase 4 — dispatcher, then consumer

Keep `SIGNAL_PRESSURE_OUTBOX_WRITE_ENABLED=false` on the pressure-worker service; writer authority belongs only to the engine.

Dispatcher:

```text
PRESSURE_OUTBOX_EXPECTED_PHASE=dispatcher
SIGNAL_PRESSURE_OUTBOX_ENABLED=true
SIGNAL_PRESSURE_OUTBOX_WRITE_ENABLED=false
SIGNAL_PRESSURE_OUTBOX_DISPATCH_ENABLED=true
STRATEGY_5SCR_PRESSURE_CONSUMER_ENABLED=false
```

Consumer:

```text
PRESSURE_OUTBOX_EXPECTED_PHASE=consumer
SIGNAL_PRESSURE_OUTBOX_ENABLED=true
SIGNAL_PRESSURE_OUTBOX_WRITE_ENABLED=false
SIGNAL_PRESSURE_OUTBOX_DISPATCH_ENABLED=true
STRATEGY_5SCR_PRESSURE_CONSUMER_ENABLED=true
```

Validate lease recovery, idempotent inbox delivery, backlog age, retries, and zero integrity violations before proceeding.

## Phase 5 — closed-candle evidence observation

Only after dispatcher/consumer stability:

```text
PRESSURE_OUTBOX_EXPECTED_PHASE=production-observe
SIGNAL_PRESSURE_OUTBOX_ENABLED=true
SIGNAL_PRESSURE_OUTBOX_WRITE_ENABLED=false
SIGNAL_PRESSURE_OUTBOX_DISPATCH_ENABLED=true
STRATEGY_5SCR_PRESSURE_CONSUMER_ENABLED=true
STRATEGY_5SCR_EVIDENCE_ENABLED=true
STRATEGY_5SCR_EVIDENCE_LIVE_ALLOWED=true
STRATEGY_5SCR_EVIDENCE_MODE=PRODUCTION_OBSERVE
STRATEGY_5SCR_OUTCOME_ENABLED=true
```

The worker preflight rejects evidence outside `production-observe`, production-observe without evidence, outcome without evidence, or any enabled execution-path flag.

Validate closed H4/H1/M15/M1 provenance, no future leakage, frozen-quote blocking, immutable evidence snapshots, and candidate/outcome precision. Finnhub spread remains estimated and cannot authorize broker execution.

## Phase 6 — separately approved execution work

This release does not authorize Phase 6. Risk reservation, final-signal outbox, command signing, EA delivery, and broker mutation require a separate review, DEMO validation, rollback drill, and explicit approval.

## Release verification commands

```powershell
python -m pytest -q tests/test_engine_pressure_rollout_preflight.py `
  tests/test_pressure_outbox_railway_deployment.py `
  tests/test_strategy_5scr_pair_admission.py `
  tests/test_strategy_5scr_pressure_radar.py `
  tests/test_pressure_radar_manifest_repository.py `
  tests/test_pressure_outbox_pipeline_integration.py `
  tests/test_5scr_episode_grouping.py `
  tests/test_5scr_episode_shadow_worker.py `
  tests/test_strategy_5scr_evidence_worker.py `
  tests/test_frozen_quote_detector.py

python -m ruff check analysis contracts pipeline services storage tests utils
```

For a deployed worker, `python -m services.pressure_outbox.preflight` is mandatory and must exit zero before the runner starts.
