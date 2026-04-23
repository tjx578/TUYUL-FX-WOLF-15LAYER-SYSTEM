# L9 Not Ready Operator Runbook

This runbook is for diagnosing `L9 not_ready` in the current runtime.

The key rule is simple:

- Do not treat `source_builder_state=not_ready` as proof that the source builder ran and failed.
- First distinguish `early-exit before builder` from `builder ran but all sources were dropped`.

## Scope

Use this runbook when:

- Phase 3 repeatedly logs `L9 constitutional FAIL`
- `missing_sources=['smc', 'liquidity', 'divergence']` appears often
- `builder_state=not_ready` appears across many symbols
- L12 keeps downgrading or blocking on structure weakness

Do not use this runbook for execution behavior. L12 remains the sole final verdict authority.

## Fast View

Treat every `L9 not_ready` as one of these buckets:

- `upstream_structure_invalid`
- `no_h1_candles`
- `divergence_insufficient_data`
- `snapshot_stale_over_15s`
- `publisher_error`
- `mixed_or_unknown`

The investigation order is:

1. Check whether L9 exited before the builder path.
2. If the builder path ran, inspect per-source diagnostics.
3. Classify into one bucket only if there is one dominant cause.
4. Use `mixed_or_unknown` only when multiple failures are equally present.

## Decision Tree

### Step 1: Did L9 early-exit before source building?

Check the structure payload assembled in Phase 3.

Runtime assembly lives in `pipeline/wolf_constitutional_pipeline.py` where `_l9_structure` is built from raw L3 fields:

- `valid = l3.get("valid", False)`
- `trend = l3.get("trend", "NEUTRAL")`
- `bos = l3.get("fvg_detected", False)`
- `choch = False`

If `structure` is empty or `structure.valid` is false, `L9SMCAnalyzer.analyze()` returns `_fail("no_structure_data")` or `_fail("invalid_structure")` before any source builder call.

Classify as:

- `upstream_structure_invalid`

Operational signal:

- `source_builder_state=not_ready`
- `available_sources=[]`
- `source_diagnostics` and `publisher_metadata` are absent or empty
- `reason=no_structure_data` or `reason=invalid_structure`

### Step 2: If L9 did not early-exit, did the builder path run?

The builder path runs only after `L9SMCAnalyzer.analyze()` passes the structure guard and assembles `source_context`.

Builder path sequence:

1. Read candles from `LiveContextBus`
2. Compute raw SMC, liquidity, and divergence fields
3. Call `SourceBuilderOrchestrator.build_for_l9(...)`
4. Merge builder output into `result`
5. Send merged payload into `L9ConstitutionalGovernor`

If `source_diagnostics` exists, the builder path ran.

If `source_diagnostics.sources` is missing entirely, treat it as a pre-builder failure and go back to Step 1.

### Step 3: Did any publisher error?

Inspect `source_diagnostics.errored` and `source_diagnostics.sources.<name>.state`.

If any source has:

- `state=errored`
- an exception string in `source_diagnostics.errored`

Classify as:

- `publisher_error`

This dominates all other buckets because the publisher did not complete successfully.

### Step 4: Is H1 candle readiness the dominant issue?

`L9SMCAnalyzer` reads H1 candles via `LiveContextBus().get_candle_history(symbol, "H1", count)`.

H1 candles are required by:

- SMC feature extraction
- liquidity publisher
- snapshot age calculation for SMC and liquidity

If H1 candles are empty or effectively unusable, liquidity publisher returns invalid with `reason=no_candles` and SMC features degrade heavily.

Classify as:

- `no_h1_candles`

Operational signal:

- `source_diagnostics.sources.liquidity.reason=no_candles`
- `source_diagnostics.sources.liquidity.state=missing`
- H1 candle count is zero or near zero for the symbol

### Step 5: Is divergence failing due to missing multi-timeframe data?

Divergence depends on candles from:

- `M5`
- `M15`
- `H1`
- `H4`

If the divergence engine exists but the required timeframes do not have enough bars, divergence reason stays `INSUFFICIENT_DATA` and the divergence source is dropped.

Classify as:

- `divergence_insufficient_data`

Operational signal:

- `source_diagnostics.sources.divergence.reason` starts with `INSUFFICIENT_DATA`
- divergence source is `missing`
- one or more of `M5/M15/H1/H4` has insufficient bars

### Step 6: Are snapshots present but stale?

`SourceBuilderOrchestrator` accepts a source only if `snapshot.age_seconds <= 15.0`.

If a source is otherwise valid but its age exceeds 15 seconds, the source is marked stale and excluded from `snapshots`.

Classify as:

- `snapshot_stale_over_15s`

Operational signal:

- `source_diagnostics.stale` is non-empty
- source state is `stale`
- publisher metadata shows age above 15 seconds

### Step 7: Use mixed when there is no single dominant cause

Classify as:

- `mixed_or_unknown`

Only when:

- multiple sources fail for different reasons without one dominant trigger
- or the payload is too incomplete to distinguish pre-builder versus post-builder failure cleanly

## Exact Call Chain

### L3 Raw Output

Raw L3 output comes from `analysis/layers/L3_technical.py` and includes fields such as:

- `valid`
- `trend`
- `fvg_detected`
- `ob_detected`

L3 constitutional wrapping in `analysis/layers/L3_constitutional.py` may degrade confidence, but the pipeline structure handoff to L9 is based on raw L3 fields, not on a separate L3 source builder.

### Phase 3 Structure Handoff

`pipeline/wolf_constitutional_pipeline.py` creates `_l9_structure` using:

- `l3.get("valid", False)`
- `l3.get("trend", "NEUTRAL")`
- `l3.get("fvg_detected", False)` as a BOS proxy
- `choch=False`

This means the first hard split is here:

- if raw L3 `valid=False`, L9 can early-exit before any source building
- if raw L3 `valid=True`, L9 enters analyzer logic and may reach the builder path

### L9 Early-Exit Gate

`analysis/layers/L9_smc.py` exits immediately when:

- `structure is None or not structure`
- `not structure.get("valid", False)`

These map to:

- `_fail("no_structure_data")`
- `_fail("invalid_structure")`

This is the definitive `early-exit before builder` split.

### L9 Builder Path

If structure passes:

1. H1 candles are loaded from `LiveContextBus`
2. BOS, FVG, OB, liquidity sweep, and divergence are computed
3. `source_context` is assembled
4. `SourceBuilderOrchestrator.build_for_l9(...)` is called

Per-source acceptance rules:

- no exception
- snapshot is not `None`
- `snapshot.valid=True`
- `snapshot.age_seconds <= 15`

If all sources are rejected, `source_builder_state` becomes `not_ready` even though the builder path did run.

### L9 Constitutional Compression

`analysis/layers/L9_constitutional.py` derives:

- `available_sources`
- `missing_sources`
- `source_builder_state`
- `source_completeness`
- `primary_structure_gap`

If `source_count <= 1`, it emits hard blocker `REQUIRED_STRUCTURE_SOURCE_MISSING`.

### Pipeline Logging Surface

`pipeline/wolf_constitutional_pipeline.py` logs L9 constitutional diagnostics including:

- `missing_sources`
- `builder_state`
- `available_sources`
- `soft_blockers`

That is the operator-facing surface to classify the bucket quickly.

## Bucket Mapping Table

| Bucket | Dominant trigger | Distinguishing signal | Primary next check |
| --- | --- | --- | --- |
| `upstream_structure_invalid` | L9 exits before builder | `reason=no_structure_data` or `reason=invalid_structure`; no useful builder diagnostics | Inspect raw L3 `valid/trend/fvg_detected` handoff |
| `no_h1_candles` | H1 candles absent for SMC/liquidity | liquidity source missing with `reason=no_candles` | Check H1 candle count and last update |
| `divergence_insufficient_data` | Multi-timeframe divergence data incomplete | divergence source missing with `INSUFFICIENT_DATA` | Check M5/M15/H1/H4 counts and age |
| `snapshot_stale_over_15s` | Valid source aged out | source listed in `stale`; metadata age > 15s | Check source timestamp freshness and bus age |
| `publisher_error` | Publisher threw exception | source state `errored` | Inspect exception and dependency init |
| `mixed_or_unknown` | No single dominant cause | multiple weak failures or incomplete payload | Capture fuller payload and retry classification |

## Operator Procedure For A Failed Symbol

For each sampled symbol with `L9 not_ready`:

1. Capture the L9 constitutional log line.
2. Capture raw L9 payload fields if available:
   - `reason`
   - `valid`
   - `source_builder_state`
   - `structure_sources`
   - `source_diagnostics`
   - `publisher_metadata`
3. Determine whether the builder path ran.
4. Assign one bucket.
5. Record one dominant next action only.

Do not mix architectural recommendations into this step.

## Canary / Debug Checklist For The Next Run

Use this checklist on the next log run.

### Per-Symbol Capture

For each failed sample symbol, collect:

- `phase1_enter`
- `l3_constitutional_result`
- raw L3 summary fields used by `_l9_structure`:
  - `valid`
  - `trend`
  - `fvg_detected`
- `L9 complete` summary line
- `L9 constitutional FAIL` or `WARN` line
- `l12_effective_verdict`

### L9 Payload Fields To Capture

Capture these fields if exposed by the API, cache, or structured logs:

- `reason`
- `valid`
- `smc`
- `smc_score`
- `liquidity_score`
- `dvg_confidence`
- `source_builder_state`
- `structure_sources`
- `source_diagnostics`
- `publisher_metadata`
- `warmup_required_bars`
- `warmup_available_bars`

### Candle Readiness Checks

For each sampled symbol, capture per timeframe:

- H1 bar count
- M5 bar count
- M15 bar count
- H4 bar count
- latest timestamp per timeframe
- age in seconds per timeframe

Minimum focus:

- `H1` for SMC and liquidity
- `M5/M15/H1/H4` for divergence

### Classification Output

For each failed symbol, write one line in this format:

```text
symbol=<SYMBOL> bucket=<BUCKET> l3_valid=<BOOL> builder_ran=<BOOL> dominant_reason=<TEXT> next_check=<TEXT>
```

Example:

```text
symbol=GBPUSD bucket=divergence_insufficient_data l3_valid=True builder_ran=True dominant_reason=divergence reason INSUFFICIENT_DATA on H4 next_check=inspect H4 candle count and age
```

### Exit Criteria For The Run

The run is useful only if it answers both questions for most failed samples:

1. Did L9 fail before the builder path or after it?
2. Which one bucket dominates each failure?

If the run cannot answer both, expand payload capture before changing thresholds or redesigning L9.

## What Not To Do

- Do not rebuild `SourceBuilderOrchestrator` first.
- Do not lower L7/L8 thresholds as a primary response to `L9 not_ready`.
- Do not treat every `not_ready` as the same defect class.
- Do not resume signoff or execution while the dominant bucket is still unknown.

## Expected Outcome

After one disciplined canary/debug run, the team should be able to say one of these with evidence:

- `Most failures are upstream_structure_invalid`
- `Most failures are no_h1_candles`
- `Most failures are divergence_insufficient_data`
- `Most failures are snapshot_stale_over_15s`
- `Most failures are publisher_error`

Only after that classification should remediation move to code changes.
