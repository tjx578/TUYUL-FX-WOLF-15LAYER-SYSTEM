# SignalThrottle Fusion V3 Contract

Status: architecture contract / implementation guardrail.  
Scope: documentation-only. No execution behavior is changed by this document.

This contract defines the non-negotiable boundary for restoring the original SignalThrottle pressure logic while preserving the newer intelligence, market validation, lifecycle, tiering, and SignalJSON execution firewall.

## Core verdict

SignalThrottle Fusion V3 is **not** a rewrite of the pipeline.

It is a formal separation of two meanings that must never be mixed:

```text
SignalThrottle Safety Clamp
= downstream over-trading control after L12/execution verdict.

SignalThrottle Pure Pressure Ledger
= upstream/parallel pressure radar built from raw throttle/intel/canary events.
```

The April-style rule is restored only inside the Pure Pressure Ledger. Modern direction intelligence, market context, Microboost, SignalWatch, SignalDecision, tiering, and execution gates remain downstream.

## Layer contract

```text
L0  Raw Event Capture
L1  Pure Pressure Ledger
L2  Block Quality Engine
L2.5 Pair Priority Tier Engine
L3  Direction Intelligence
L4  Radar / Market Structure Context
L5  Microboost Timing Layer
L6  SignalWatch Router
L7  SignalDecision / Lifecycle Finalizer
L8  SignalJSON Execution Firewall
```

## Non-negotiable invariants

### 1. Pure Pressure Ledger is gap-agnostic

```text
same symbol  = continue the pure pressure block
other symbol = close the current pure pressure block
time gap     = quality/heat metadata only; never split reason
```

A same-symbol run with a large gap and no other symbol interruption is still one Pure Pressure Block.

Implementation guardrail:

```python
build_pure_pressure_blocks(events) == build_pressure_blocks(events, max_gap_seconds=None)
```

Runtime note:

```text
PurePressureLedger = diagnostic pressure truth, pair-rotation-only.
V1CleanBlockLedger = production clean-block source, scanner-cycle-aware pair persistence.
```

The production scanner emits many pairs in a repeated cycle. A different pair
between two same-symbol observations can be scanner interleaving, not proof
that the first pair lost pressure. The V1 clean-block ledger must therefore
preserve same-symbol persistence across scanner interleaving and split that
symbol only after it goes quiet beyond the scanner-cycle window.

### 2. Burst/Microboost is allowed to be gap-sensitive

Microboost measures fresh timing pressure, not long-context pressure.

```text
PurePressureBlock = pair-rotation-only, gap-agnostic
MicroboostBlock   = timing/density burst, gap-sensitive
```

Do not use Microboost thresholds as the only gate for clean pressure validity.

### 3. NO_TRADE blocks orders, not radar

```text
NO_TRADE may block SignalJSON execution.
NO_TRADE must not block pressure capture, pure ledger, radar diagnostics, or terminal NO_TRADE_REASONED updates.
```

Pressure should remain visible even when no order is allowed.

### 4. Microboost never resolves final direction

Microboost is timing/location evidence only.

Required output contract:

```text
direction           = UNRESOLVED
valid_for_execution = false
next_stage          = SIGNAL_WATCH
```

Raw pressure color may be carried as `raw_pressure_direction`, but final trade direction belongs to downstream layers.

### 5. SignalWatch is not execution

SignalWatch may publish lifecycle/watch state. It must not set final execution permission.

Required watch defaults:

```text
final_direction      = WAIT
valid_for_execution  = false
execution_valid_now  = false
is_final_signal      = false
```

### 6. Pair Tier is advisory only

Pair Tier ranks analysis priority. It never relaxes L12, SignalJSON, RR, spread, structure, or execution gates.

```text
T0/T1/T2/T3 = analysis priority
not         = permission to execute
```

### 7. Market context has two strictness levels

```text
Radar context     = may be partial; enough for watch/tier explanation.
Execution context = strict; requires price, M15/H1/structure/spread/RR completeness.
```

Do not make M15 close mandatory for all radar/watch states. M15 confirmation is required for conflict/counter/reversal/absorption cases and optional for clean continuation when higher-timeframe structure is already aligned.

### 8. SignalJSON remains the final firewall

Fusion V3 cannot emit execution-ready final SignalJSON directly.

Initial rollout must keep:

```env
SIGNAL_THROTTLE_FUSION_EXECUTION_ENABLED=false
```

Only the existing SignalJSON gate adapter and execution gates may publish `valid_for_execution=true`.

## Required outputs

A production implementation should emit these observability surfaces:

```text
[PurePressureLedger]
[SignalThrottleFusionV3]
[PairPriorityTier]
```

Required fields:

```text
gap_split_applied=false
split_rule=PAIR_ROTATION_ONLY
gap_policy=QUALITY_ONLY
pure_pressure_score
heat_score
pressure_class
dynamic_pressure_tier
execution_tier=WAIT
source_clean_block_id
source_pressure_block_id
valid_for_execution=false
```

Required V1 clean-block fields:

```text
clean_block_rule=SCANNER_CYCLE_AWARE_PAIR_PERSISTENCE_DURATION_GE_THRESHOLD
legacy_pure_block_rule=PAIR_ROTATION_ONLY_GAP_AGNOSTIC_DURATION_GE_THRESHOLD
scanner_cycle_aware=true
split_rule=SCANNER_CYCLE_AWARE_PAIR_PERSISTENCE
gap_policy=SCANNER_CYCLE_QUALITY_ONLY
source_clean_block_id
valid_for_execution=false
```

## Required implementation tests

```text
1. Same-symbol huge-gap block with no pair interruption remains one pure block.
2. Different-symbol interruption splits the pure block.
3. Scanner-cycle clean blocks preserve repeated same-symbol pressure across scanner interleaving.
4. Pure block without direction produces PURE_RADAR_ONLY or NO_TRADE_REASONED, not silence.
5. Microboost remains gap-sensitive and direction UNRESOLVED.
6. Pair tier can promote low-static-tier pair if pure pressure is dominant.
7. Fusion output never emits valid_for_execution=true.
8. SignalJSON gate tests remain green.
9. UniverseRanking legacy tests remain green.
```

## Forbidden changes

```text
Do not rewrite constitution/signal_throttle.py into a market-decision engine.
Do not let pure pressure blocks emit orders.
Do not use Microboost gap-sensitive blocks as the V1 clean-block source of truth.
Do not make Microboost a direction resolver.
Do not make Pair Tier override L12.
Do not make M15 close a universal requirement.
Do not bypass SignalJSON execution gates.
```

## Final sentence

SignalThrottle Fusion V3 restores the April pressure-ledger logic as the truth source for pair pressure, then lets the modern pipeline decide direction, structure, tier, lifecycle, and execution safety.
