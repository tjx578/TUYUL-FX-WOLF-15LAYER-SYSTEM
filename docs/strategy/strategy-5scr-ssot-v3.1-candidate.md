# Strategy 5S-CR SSOT V3.1 Candidate — Analysis Admission

Status: **candidate / shadow-only**. This document does not promote V3.1 into
execution authority and does not replace the current production SSOT.

## Normative decision

Canonical PairAdmission remains raw-ledger-only. Absence of canonical raw
PairAdmission must not discard a mature directional advisory from analysis.

```text
CANONICAL_RAW
  -> full canonical analysis
  -> may reach a later promotion path only through every existing gate

MATURE_ADVISORY
  -> full shadow analysis
  -> closed-candle evidence and shadow candidate only
  -> risk_authority=false
  -> execution_authority=false
```

`MATURE_ADVISORY` never becomes PairAdmission, a FinalSignal, a risk
reservation or an ExecutionCommand.

## StrategyAnalysisAdmissionV1

The executable contract is defined in
`contracts/strategy_5scr_analysis_admission.py` with rule version
`strategy-analysis-admission.v1`.

An admission records:

- admission class and status;
- canonical or derived source authority;
- pressure direction and direction-lineage alignment;
- advisory maturity and context alignment;
- current analysis state and next required stage;
- evidence-prefetch and shadow-tradeplan permissions;
- deterministic logical identity, material-state hash and evidence hash;
- immutable `final_direction=WAIT`, `valid_for_execution=false`,
  `risk_authority=false`, and `execution_authority=false`.

## Advisory maturity policy

Maturity is calculated from analyzer block evidence, never emitted log-row
count:

```text
MATURE  = duration >= 300 seconds and deduplicated effective events >= 3
EXTREME = duration >= 1800 seconds and deduplicated effective events >= 100
```

A grant additionally requires:

- derived/CANARY advisory source;
- aligned BUY or SELL direction lineage;
- non-expired pressure;
- `raw_direction_eligible_for_context_resolution=true`;
- material context already present or requestable.

Direction conflict produces `SUSPENDED` and
`ADVISORY_WAITING_PRESSURE_RESOLUTION`; it cannot create a BUY or SELL
hypothesis.

## Price and context semantics

`PRICE_FROZEN`, warming-up or insufficient-history data does not delete a
granted advisory. It produces `ADVISORY_WAITING_PRICE_QUALITY`. Historical
closed H4/H1/M15/M1 evidence may still be prefetched, but no live-entry
geometry is authoritative.

Countertrend or blocked context preserves the pressure hypothesis and requests
strict H1/M15 proof. Lack of proof resolves to WAIT/NO_TRADE in shadow; it does
not reverse pressure into an opposite strategy.

## Durable lifecycle and queue

The worker reads `pressure_radar_events`, not the canonical pressure outbox.
This preserves the existing PairAdmission and pressure-outbox contracts.

Migration `20260826_01` creates an isolated admission ledger, append-only
evaluation history, durable evidence jobs and immutable shadow snapshots.
Every database artifact is CHECK-constrained against risk or execution
authority.

The first granted advisory opens or attaches to `StrategyLifecycleV2`.
Subsequent sticky emissions retain the same logical admission ID and lifecycle.
Material state changes (for example frozen quote becoming usable) get a new
evidence job keyed by `analysis_material_hash`, not by telemetry emission
count.

If canonical raw PairAdmission arrives later, the canonical event attaches to
the active market episode. It must not create a second strategy lifecycle.

## Analysis states

```text
ADVISORY_OBSERVED_IMMATURE
ADVISORY_ANALYSIS_QUEUED
ADVISORY_ANALYSIS_READY
ADVISORY_WAITING_PRICE_QUALITY
ADVISORY_WAITING_CONTEXT
ADVISORY_WAITING_PRESSURE_RESOLUTION
ADVISORY_WAITING_H1
ADVISORY_WAITING_M15
ADVISORY_SHADOW_CANDIDATE
ADVISORY_TERMINAL_NO_TRADE
ADVISORY_INVALIDATED
ADVISORY_EXPIRED
```

## Rollout

The feature defaults off. Activation requires:

1. migration `20260826_01` applied;
2. durable pressure-radar writes active on the engine;
3. `STRATEGY_5SCR_ANALYSIS_ADMISSION_V1_ENABLED=true` on the pressure worker;
4. `STRATEGY_5SCR_ANALYSIS_ADMISSION_V1_SHADOW_ONLY=true`;
5. all execution, command, trade-outbox and risk-reservation flags off;
6. successful pressure-worker preflight and shadow acceptance monitoring.

Any non-shadow or active execution-plane combination fails at startup.

## Locked USDCHF interpretation

The audited USDCHF episode is a SELL analysis candidate, not an executable
SELL. Its canonical PairAdmission status remains
`NOT_APPLICABLE_NO_RAW_AUTHORITY_BLOCK`, while its higher admission may be
`MATURE_ADVISORY / GRANTED`. Frozen price or context conflict keeps the final
decision at WAIT and cannot create risk or command authority.
