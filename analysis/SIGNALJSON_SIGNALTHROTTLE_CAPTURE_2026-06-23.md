# SignalJSON / SignalThrottle production capture

Capture date: 2026-06-23 WITA

## Deployment identity

- Deployment: `85760c4b-0299-4299-b3de-66d43f082e82`
- Commit: `5d9f1a49f87f89482d4f75cc74586556804510d8`
- Captured UTC range: `2026-06-22T13:58:48Z` to `2026-06-22T17:43:27Z`
- Runtime activity rechecked at: `2026-06-22T17:55:54Z`

The capture contains one deployment only. The runtime recheck showed the analysis
cycle was still active after the capture, so empty SignalJSON markers are not a
service-outage artifact.

## Marker counts

| Marker | Count |
| --- | ---: |
| `signal_intelligence_flag_snapshot` | 1 |
| `SignalThrottleIntel` | 189 |
| `signal_throttle_check` | at least 5000 (capture cap reached) |
| `microboost_watch_candidate_diagnostic` | 21 |
| `SignalDecisionUpdateJSON` | 54 |
| `SignalWatchJSON` | 0 |
| `SignalJSON` | 0 |
| execution-gate sidecar | 0 |
| error-level log | 0 |

## Verified funnel

1. All 5000 captured throttle checks carried a native BUY/SELL direction.
2. SignalThrottleIntel produced 147 allowed candidates and 42 allowed-quorum
   pending-validation events; all retained `final_direction=WAIT`.
3. The 21 Microboost diagnostics all had native block direction, but each block
   had only one effective tick and failed tick and duration thresholds.
4. The 54 allowed-quorum candidates were terminalized safely as
   `NO_TRADE_REASONED` DecisionUpdates. All had `valid_for_execution=false`,
   `tradeplan_valid=false`, and `execution_valid_now=false`.
5. No candidate reached an official Watch or execution-grade final signal.

## Findings

### Confirmed observability mismatch

The pipeline calculated pressure provenance and `watch_promotion_blockers`, but
`build_signal_json_event()` dropped those values during the dict-to-event rebuild.
Production DecisionUpdates therefore reported the safe terminal result without
the exact promotion blockers.

Fix: preserve pressure/quorum context, blocker counts, and Microboost state in the
emitted DecisionUpdate schema.

### Incomplete startup evidence

The startup snapshot did not expose the Phase 3 preview switch or the main
SignalJSON emission and gate switches. This made a zero-output capture harder to
distinguish from a disabled emitter.

Fix: include market-structure preview, emitter, gate, and terminal-decision flags
in `signal_intelligence_flag_snapshot`.

### Pressure-block fragmentation bottleneck

The current analyzer treats an intervening symbol as a hard rotation interrupt.
On a multi-symbol production scan this fragmented 543 of 549 recent pressure
events into blocks, including 537 one-tick blocks.

A replay that ignored cross-symbol rotations still produced no eligible
Microboost: per-symbol density remained below the configured minimum. Therefore,
removing rotation interrupts or lowering thresholds alone would manufacture more
Watch candidates without proving execution quality.

Recommended follow-up: build a separately flagged, per-symbol rolling burst lane
for Microboost classification, retain the existing lifecycle blocks, and compare
both lanes in shadow diagnostics before changing Watch promotion behavior.

## Verdict

`SignalJSON=0` is correct for this sample. The active bottleneck is candidate
quality and Watch promotion, not direction recovery and not the final safety
barrier. No execution gate should be relaxed to force output.
