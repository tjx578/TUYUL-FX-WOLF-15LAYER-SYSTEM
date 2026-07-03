# 01 — Raw Capture and Pure Pressure Ledger

Status: layer contract / implementation guide.

## Purpose

This section protects the original SignalThrottle pressure logic.

The Pure Pressure Ledger answers only:

```text
Which pair is repeatedly appearing in the pressure stream?
How long did that same-pair sequence last?
How many events occurred?
Was the sequence interrupted by another pair?
How fresh or dense is the block?
```

It does **not** answer:

```text
BUY or SELL final?
Is this entry-ready?
What is the RR?
Is this SignalJSON executable?
```

## Input streams

Raw capture may normalize multiple sources into one internal event model:

```text
[SignalThrottle] THROTTLED
[SignalThrottle] allowed
[SignalThrottle] downgraded to HOLD
[SignalThrottleIntel]
event=signal_throttle_check
```

Every normalized event must explicitly carry:

```text
symbol
source_stream
event_type
direction or raw_direction
eligible_for_pressure_block
eligible_for_execution
execution_block_reason
```

## Pure block rule

Pure blocks are split only by pair rotation.

```text
same symbol  = continue current pure block
other symbol = close current pure block
time gap     = metadata only
```

Implementation guardrail:

```python
def build_pure_pressure_blocks(events):
    return build_pressure_blocks(events, max_gap_seconds=None)
```

## Why gap must not split pure pressure

A long same-pair sequence with a large gap may still represent a valid contextual pressure block. The gap lowers heat/freshness, but it must not destroy the historical pressure ledger.

Correct interpretation:

```text
large gap + same symbol + no other pair = one pure block, lower heat score
```

Wrong interpretation:

```text
large gap = automatically split clean pressure block
```

## Output contract

Pure ledger output should include:

```text
pure_pressure_blocks
pure_top_blocks
pure_active_candidate
pure_block_count
pure_block_ledger
```

Each block should include:

```text
symbol
source_pressure_block_id
start_utc
end_utc
duration_seconds
event_count
density_per_minute
max_gap_seconds
avg_gap_seconds optional until implemented in runtime payload
gap_split_applied=false
split_rule=PAIR_ROTATION_ONLY
gap_policy=QUALITY_ONLY
raw_pressure_direction
direction_status
valid_for_execution=false
final_direction=WAIT
```

## Field implementation status

```text
Implemented / existing-style fields:
- symbol
- start_utc / end_utc equivalents
- duration_seconds
- event_count / events equivalents
- density_per_minute / effective_density_per_minute equivalents
- max_gap_seconds equivalents

Contract-required new/normalized fields:
- source_pressure_block_id
- gap_split_applied=false
- split_rule=PAIR_ROTATION_ONLY
- gap_policy=QUALITY_ONLY
- direction_status

Optional until runtime support is added:
- avg_gap_seconds
```

`avg_gap_seconds` is a recommended observability field. It should not block the first implementation if the runtime block object only exposes `max_gap_seconds` or equivalent gap metadata.

## Bias guardrails

Do not allow these mistakes:

```text
Do not use gap-sensitive blocks as pure ledger.
Do not promote pure blocks directly to SignalJSON.
Do not discard NO_TRADE pressure.
Do not require M15/H1 context before recording pure pressure.
Do not let Pair Tier change the raw ledger.
```

## Required tests

```text
same symbol + huge gap + no other pair = one pure block
different symbol between same symbol events = split block
same-second collision behavior remains documented and stable
NO_TRADE pressure can still create pressure telemetry
pure block never emits valid_for_execution=true
```