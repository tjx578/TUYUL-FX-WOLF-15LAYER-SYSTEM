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
deployment_id
scanner_cycle_id
scanner_epoch
observed_cycle_index
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
avg_gap_seconds
gap_split_applied=false
split_rule=PAIR_ROTATION_ONLY
gap_policy=QUALITY_ONLY
raw_pressure_direction
direction_status
valid_for_execution=false
final_direction=WAIT
```

`avg_gap_seconds` is ledger metadata only. It can explain whether a block is
fresh or sparse, but it must not become a split rule for the Pure Pressure
Ledger.

## Field implementation status

```text
Implemented / existing-style fields:
- symbol
- start_utc / end_utc equivalents
- duration_seconds
- event_count / events equivalents
- density_per_minute / effective_density_per_minute equivalents
- max_gap_seconds
- avg_gap_seconds
- source_pressure_block_id
- gap_split_applied=false
- split_rule=PAIR_ROTATION_ONLY
- gap_policy=QUALITY_ONLY
- raw_pressure_direction
- valid_for_execution=false
- final_direction=WAIT

Contract fields that may still need naming normalization at downstream edges:
- direction_status
- source_signal_throttle_event_range
```

`avg_gap_seconds` is implemented in the runtime block payload. It remains
quality metadata only; it must not be used to split a Pure Pressure Block.

## V1 clean block ledger

The runtime also publishes a production clean-block ledger for scanner-cycle
streams. This is intentionally separate from the Pure Pressure Ledger:

```text
Pure Pressure Ledger
= diagnostic pressure truth
= pair-rotation-only and gap-agnostic

V1 Clean Block Ledger
= production clean-block source
= scanner-cycle-aware same-symbol persistence
```

Scanner output rotates through many pairs. A different pair between two
same-symbol events can be scheduler interleaving, not a true pressure stop.
For V1 clean blocks, the split rule is therefore:

```text
same symbol inside scanner-cycle window = continue that symbol's clean block
same symbol quiet beyond scanner window = start a new clean block for that symbol
different symbol                         = scanner interleaving, not a split reason
```

Required V1 fields:

```text
clean_block_rule=SCANNER_CYCLE_AWARE_PAIR_PERSISTENCE_DURATION_GE_THRESHOLD
legacy_pure_block_rule=PAIR_ROTATION_ONLY_GAP_AGNOSTIC_DURATION_GE_THRESHOLD
scanner_cycle_aware=true
split_rule=SCANNER_CYCLE_AWARE_PAIR_PERSISTENCE
gap_policy=SCANNER_CYCLE_QUALITY_ONLY
deployment_ids
scanner_cycle_ids
scanner_epoch_start_utc
scanner_epoch_end_utc
observed_cycle_index_min
observed_cycle_index_max
source_clean_block_id
source_pressure_block_id
valid_for_execution=false
```

## Bias guardrails

Do not allow these mistakes:

```text
Do not use gap-sensitive blocks as pure ledger.
Do not use hard pair rotation as the only V1 clean-block source for scanner-cycle runtime.
Do not promote pure blocks directly to SignalJSON.
Do not discard NO_TRADE pressure.
Do not require M15/H1 context before recording pure pressure.
Do not let Pair Tier change the raw ledger.
```

## Required tests

```text
same symbol + huge gap + no other pair = one pure block
different symbol between same symbol events = split block
scanner-cycle interleaving between same-symbol events = one V1 clean block
same-second collision behavior remains documented and stable
NO_TRADE pressure can still create pressure telemetry
pure block never emits valid_for_execution=true
```
