# 04 — Microboost, SignalWatch, and SignalDecision

Status: layer contract / implementation guide.

## Purpose

This section protects the lifecycle boundary between timing evidence, watch output, and decision updates.

```text
Microboost     = timing + location evidence
SignalWatch    = non-executable lifecycle/watch state
SignalDecision = direction/structure/tradeplan lifecycle explanation
SignalJSON     = final execution product only after gates pass
```

## Microboost contract

Microboost must remain a pure-stage timing layer.

Required invariants:

```text
direction=UNRESOLVED
valid_for_execution=false
next_stage=SIGNAL_WATCH
```

Microboost may carry:

```text
symbol
raw_pressure_direction
phase_unpriced
phase_priced
price_position
start_utc
end_utc
duration_minutes
effective_tick_count
effective_density_per_minute
requires_market_context
source_clean_block_id
source_pressure_block_id
```

Microboost must not carry or decide:

```text
final_direction
entry permission
RR validity
tradeplan validity
execution readiness
order permission
```

## Pure block vs Microboost block

```text
Pure block      = gap-agnostic, pair-rotation-only
Microboost block = gap-sensitive, density/timing burst
```

A pure block may be valid while Microboost is absent.

Correct behavior:

```text
valid pure pressure + no hot microboost = PURE_RADAR_ONLY or CLEAN_BLOCK_WATCH_PENDING
```

Wrong behavior:

```text
no microboost = no pressure exists
```

## SignalWatch contract

SignalWatch is allowed to publish watch state but not execution state.

Required defaults:

```text
final_direction=WAIT
valid_for_execution=false
execution_valid_now=false
is_final_signal=false
signal_valid=false unless explicitly promoted by decision layer
```

Watch statuses may include:

```text
PURE_RADAR_ONLY
CLEAN_BLOCK_WATCH_PENDING_CONTEXT
CLEAN_BLOCK_WATCH_PENDING_DIRECTION
CLEAN_BLOCK_BUY_WATCH
CLEAN_BLOCK_SELL_WATCH
MICROBOOST_WATCH
WAIT_DIRECTION_CONFLICT
```

## SignalDecision contract

SignalDecision must explain lifecycle progression or blockage.

Allowed terminal non-execution states:

```text
NO_TRADE_REASONED
PURE_RADAR_EXPIRED
WAIT_STRUCTURE_OR_NEXT_M15
WAIT_M15_CLOSE_OR_STRUCTURE_TARGET
PENDING_WATCH_EXPIRED
FINAL_VALID_EXECUTION_DEFERRED
FINAL_VALID_WAIT_STRUCTURE_TARGET
FINAL_VALID_WAIT_RETEST
```

DecisionUpdate should be emitted when pressure was seen but not promoted.

Required diagnostic fields:

```text
pressure_seen
pressure_event_count
microboost_detected
watch_promotion_blockers
direction_validation_status
terminal_status
valid_for_execution=false
reason
```

## Source lineage requirement

Every Microboost/Watch/Decision derived from SignalThrottle pressure must preserve lineage:

```text
source_clean_block_id
source_pressure_block_id
source_signal_throttle_event_range
clean_block_valid
clean_block_start_utc
clean_block_end_utc
clean_block_duration_seconds
clean_block_event_count
```

If lineage is missing, emit diagnostic instead of pretending the event is valid.

## Bias guardrails

```text
Do not make Microboost choose pairs by itself.
Do not let Microboost resolve final direction.
Do not suppress pressure just because Microboost threshold failed.
Do not emit SignalWatch without source lineage.
Do not emit SignalJSON directly from Microboost.
Do not allow pending watches to disappear silently.
```

## Required tests

```text
Microboost core output always direction UNRESOLVED
Microboost without source_clean_block_id is blocked/diagnostic
pure pressure without microboost emits radar/decision diagnostic, not silence
Watch payload remains non-executable
DecisionUpdate emitted for NO_TRADE_REASONED pressure
Pending watch expiry emits terminal lifecycle update
```