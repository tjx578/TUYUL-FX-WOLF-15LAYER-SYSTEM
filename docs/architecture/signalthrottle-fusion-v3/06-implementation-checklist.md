# 06 — Implementation Checklist

Status: engineering checklist / review gate.

Use this checklist before approving any code change related to SignalThrottle Fusion V3.

## A. Contract checks

```text
[ ] Does the patch preserve the Pure Pressure Ledger rule?
[ ] Does the patch keep time gap as quality metadata only?
[ ] Does the patch keep Microboost gap-sensitive but not pure-ledger-sensitive?
[ ] Does the patch keep SignalWatch non-executable?
[ ] Does the patch keep Pair Tier advisory-only?
[ ] Does the patch keep SignalJSON gate authority intact?
```

## B. Raw capture checks

```text
[ ] THROTTLED events are normalized.
[ ] ALLOWED events are normalized.
[ ] DOWNGRADED_TO_HOLD events are normalized.
[ ] SignalThrottleIntel events are normalized.
[ ] signal_throttle_check / PRESSURE_CANARY events are normalized.
[ ] eligible_for_pressure_block is explicit.
[ ] eligible_for_execution is explicit.
[ ] deployment_id is explicit.
[ ] scanner_cycle_id / scanner_epoch / observed_cycle_index are explicit for runtime events.
```

## C. Pure ledger checks

```text
[ ] build_pure_pressure_blocks exists or equivalent wrapper is documented.
[ ] Pure block source uses max_gap_seconds=None.
[ ] Pure block split reason is PAIR_ROTATION_ONLY.
[ ] Pure block output has source_pressure_block_id.
[ ] Pure block output has gap_split_applied=false.
[ ] Pure block output never sets valid_for_execution=true.
```

## C2. V1 clean block ledger checks

```text
[ ] V1 clean block source is scanner-cycle-aware for multi-pair scanner runtime.
[ ] V1 clean block rule is SCANNER_CYCLE_AWARE_PAIR_PERSISTENCE_DURATION_GE_THRESHOLD.
[ ] V1 clean blocks preserve same-symbol persistence across scanner interleaving.
[ ] V1 clean blocks do not use Microboost burst blocks as source of truth.
[ ] V1 clean block output has source_clean_block_id.
[ ] V1 clean block output carries scanner-cycle lineage metadata.
[ ] V1 clean block output never sets valid_for_execution=true.
```

## D. Block quality checks

```text
[ ] pure_pressure_score exists.
[ ] heat_score exists.
[ ] gap quality affects heat/quality, not block existence.
[ ] long low-density blocks become contextual radar, not execution.
[ ] short dense blocks can become timing/burst candidates, not pure truth.
```

## E. Pair tier checks

```text
[ ] Pair Tier reads Pure Pressure Ledger.
[ ] Pair Tier may read UniverseRanking.
[ ] Pair Tier emits advisory_only=true.
[ ] Pair Tier output has execution_tier=WAIT unless downstream execution gates validate.
[ ] Static pair tier has limited weight.
[ ] Low-static-tier but high-pressure pair can be promoted.
```

## F. Direction and context checks

```text
[ ] Missing direction produces PURE_RADAR_ONLY, not silence.
[ ] Direction conflict produces WAIT_DIRECTION_CONFLICT.
[ ] Radar context and execution context are separated.
[ ] Radar context does not require complete M15/H1 execution fields.
[ ] Execution context remains strict.
[ ] M15 close policy is dynamic, not universal.
```

## G. Microboost checks

```text
[ ] Microboost direction remains UNRESOLVED.
[ ] Microboost valid_for_execution remains false.
[ ] Microboost next_stage remains SIGNAL_WATCH.
[ ] Microboost has source_clean_block_id.
[ ] Microboost absence does not delete pure pressure.
```

## H. Watch and decision checks

```text
[ ] SignalWatch final_direction remains WAIT unless existing contract explicitly allows otherwise.
[ ] SignalWatch valid_for_execution remains false.
[ ] SignalWatch has source lineage.
[ ] SignalDecisionUpdate emits NO_TRADE_REASONED when pressure was seen but execution is not allowed.
[ ] Pending watches expire with explanation, not silence.
```

## I. Execution firewall checks

```text
[ ] Fusion code cannot emit final SignalJSON directly.
[ ] SignalJSON gate adapter remains enabled/enforced by default.
[ ] valid_for_execution=true only appears after existing execution gates allow it.
[ ] provisional RR fallback remains non-executable.
[ ] RR/structure/spread/news/pattern/live-RR/no-chase gates remain authoritative.
```

## J. Minimum test suite additions

```text
[ ] test_pure_pressure_same_symbol_huge_gap_stays_one_block
[ ] test_pure_pressure_pair_rotation_splits_block
[ ] test_pure_pressure_without_direction_emits_radar_only
[ ] test_microboost_remains_unresolved_and_non_executable
[ ] test_pair_tier_pressure_can_outrank_static_pair_tier
[ ] test_radar_context_partial_does_not_block_pure_radar
[ ] test_execution_context_still_requires_strict_fields
[ ] test_fusion_outputs_no_valid_for_execution_true
[ ] test_no_trade_reasoned_emits_when_pressure_seen_but_not_promoted
```

## K. Rollout gate

Do not enable production behavior until all are true:

```text
[ ] Documentation merged.
[ ] Tests merged.
[ ] Pure ledger diagnostic canary clean.
[ ] Pair tier advisory canary clean.
[ ] SignalJSON count stable.
[ ] No unexpected valid_for_execution=true.
[ ] Operator logs show clear reason for radar/watch/decision states.
```

## Final review rule

If a future patch makes the system produce more executable signals but less explanation, reject it.

If a future patch makes the system produce better pressure visibility without weakening execution gates, it is aligned with Fusion V3.
