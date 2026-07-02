# 02 — Block Quality and Pair Tiering

Status: layer contract / implementation guide.

## Purpose

Block Quality and Pair Tiering decide analysis priority, not execution permission.

```text
Block Quality = how strong and fresh the pressure is.
Pair Tier     = which pair deserves analysis first.
Execution     = decided later by SignalJSON gates.
```

## Two-score model

Fusion V3 separates long-context pressure from fresh timing pressure.

```text
pure_pressure_score = dominance of the pair pressure sequence
heat_score          = freshness, density, compression, and timing quality
```

A long block may have high pure pressure but low heat. A short dense block may have moderate pure pressure but high heat.

## Block Quality fields

Every block quality result should include:

```text
pure_pressure_score
heat_score
sequence_score
duration_score
event_count_score
density_score
gap_quality_score
source_purity_score
pressure_class
pressure_grade
pressure_temperature
```

Recommended pressure classes:

```text
LONG_CONTEXTUAL_RADAR
ACTIVE_PRESSURE_RADAR
HOT_BURST_PRESSURE
TACTICAL_RADAR
LOW_ACTIVITY_RADAR
SPARSE_ARCHIVE
```

## Gap interpretation

Gap is not a split reason for Pure Pressure Ledger. Gap is a quality input.

```text
large gap = lower heat_score
large gap != invalid pure block
```

## Pair Tier purpose

Pair Tier answers:

```text
Which pair should the system analyze first?
Which pair is primary watch?
Which pair is only radar context?
Which pair can be archived for now?
```

Pair Tier does **not** answer:

```text
Is this trade executable?
Can SignalJSON be emitted?
Should L12 be overridden?
```

## Tier types

### Static Pair Tier

Static pair tier reflects pair character:

```text
S = major/gold/high liquidity/high attention
A = liquid majors/crosses
B = volatile crosses/theme-sensitive pairs
C = minor/exotic/spread-sensitive pairs
```

Static tier should have low score weight. The system must not blindly prefer popular pairs over real pressure.

### Dynamic Pressure Tier

Dynamic pressure tier reflects current SignalThrottle pressure:

```text
T0_INSTITUTIONAL_PRIORITY
T1_PRIMARY_WATCH
T2_CONTEXTUAL_RADAR
T3_ARCHIVE
```

### Execution Tier

Execution tier remains downstream and may only be assigned after direction, structure, RR, spread, and SignalJSON gates are ready.

## Recommended score formula

```python
pair_priority_score = (
    pure_pressure_score * 0.35 +
    block_quality_score * 0.20 +
    heat_score * 0.15 +
    direction_confidence_score * 0.15 +
    structure_relevance_score * 0.10 +
    static_pair_weight * 0.05
)
```

## Output contract

```json
{
  "event": "pair_priority_tier",
  "symbol": "USDJPY",
  "static_pair_tier": "S",
  "dynamic_pressure_tier": "T1_PRIMARY_WATCH",
  "execution_tier": "WAIT",
  "pair_priority_score": 78.4,
  "advisory_only": true,
  "valid_for_execution": false,
  "reason": [
    "pure_pressure_block_valid",
    "long_duration",
    "heat_not_fresh_enough",
    "direction_pending",
    "structure_pending"
  ]
}
```

## Integration rule

Pair Tier should use `UniverseRankingEngine` as one input, not replace it.

```text
UniverseRanking = relative strength / basket context
PairPriorityTier = universe ranking + pure pressure + microboost + direction + context
```

## Bias guardrails

```text
Do not let static tier dominate pressure reality.
Do not let Pair Tier set valid_for_execution=true.
Do not let Pair Tier override L12.
Do not let Pair Tier mutate pure pressure blocks.
Do not hide low-static-tier pairs that form dominant clean pressure.
```

## Required tests

```text
low static tier + strong pure pressure can outrank high static tier with weak pressure
T0/T1/T2/T3 output remains advisory-only
execution_tier remains WAIT unless downstream gates explicitly validate
UniverseRanking legacy tests remain unchanged
```