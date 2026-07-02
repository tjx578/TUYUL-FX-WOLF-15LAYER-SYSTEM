# 03 — Direction and Market Context

Status: layer contract / implementation guide.

## Purpose

Direction Intelligence and Market Context decide whether pressure can become a watch, decision, or final execution candidate.

They must not rewrite the Pure Pressure Ledger.

```text
Pure Pressure Ledger = pressure exists
Direction Intelligence = pressure has a directional color or conflict
Market Context = price/structure supports, blocks, or delays interpretation
```

## Direction contract

Direction may come from:

```text
raw_direction
SignalThrottleIntel
allowed quorum
pressure canary recovery
family lineage
market structure agreement
```

Direction status should be explicit:

```text
UNRESOLVED
RAW_RECOVERED
CANARY_QUORUM
STRUCTURE_ALIGNED
CONFLICT
```

A missing direction must not delete the pressure block.

Correct behavior:

```text
valid pressure + no direction = PURE_RADAR_ONLY
```

Wrong behavior:

```text
valid pressure + no direction = no output
```

## Market context split

Fusion V3 requires two validation levels.

### Radar Context

Radar context may be partial. It is enough for explanation, tiering, and watch preparation.

Radar context may include:

```text
price_position
main_support / main_resistance
key_support / key_resistance
h4_phase / d1_phase
market_bias / trend_direction
spread_normal if available
session / volatility if available
```

Radar context must not require all M15/H1 execution fields.

### Execution Context

Execution context remains strict.

Execution validation may require:

```text
price_at_signal_start
price_at_5m_confirm
price_at_signal_end
m15_phase
h1_phase
spread_normal
support/resistance ladder
RR targets
entry reference
selected stop
```

## M15 close policy

M15 close is not universal.

```text
REQUIRED:
- counter-entry
- reversal
- absorption
- direction conflict
- rejection confirmation
- failed breakout / failed breakdown

OPTIONAL:
- clean continuation
- HTF-aligned directional pressure
- structure target already valid

NOT_APPLICABLE:
- pure radar only
- no direction
- tier-only analysis
```

## Output contract

Direction + context output should include:

```text
direction_status
raw_pressure_direction
validated_direction
structure_context_status
radar_context_ready
execution_context_ready
requires_m15_close
requires_m15_close_policy
waiting_for
reason
valid_for_execution=false unless SignalJSON gate allows it
```

## Bias guardrails

```text
Do not discard pressure because direction is missing.
Do not make M15 close mandatory for all watch states.
Do not treat Radar Context as Execution Context.
Do not fabricate missing market prices.
Do not allow direction recovery to bypass structure validation.
```

## Required tests

```text
valid pure pressure + missing direction => PURE_RADAR_ONLY
valid pressure + direction conflict => WAIT_DIRECTION_CONFLICT
radar context can pass with HTF/structure but missing M15
execution context still fails when M15/price/spread fields are missing
M15 close required only for conflict/counter/reversal/absorption policies
```