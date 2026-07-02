# 05 — Execution Firewall and Rollout

Status: production rollout contract.

## Purpose

This section ensures SignalThrottle Fusion V3 improves observability and prioritization without accidentally creating executable signals.

## Execution authority

Fusion V3 has no direct execution authority.

```text
Fusion V3 may emit diagnostics, tier, watch, and decision updates.
Fusion V3 may not emit final executable SignalJSON.
```

Only the existing SignalJSON gate adapter and execution gates may allow:

```text
valid_for_execution=true
execution_valid_now=true
status=FINAL_EXECUTION_READY
```

## Initial feature flags

Recommended rollout defaults:

```env
SIGNAL_THROTTLE_FUSION_V3_ENABLED=false
SIGNAL_THROTTLE_FUSION_DIAGNOSTIC_ENABLED=true
SIGNAL_THROTTLE_FUSION_EXECUTION_ENABLED=false
SIGNAL_THROTTLE_PURE_LEDGER_ENABLED=true
SIGNAL_THROTTLE_PURE_LEDGER_GAP_AGNOSTIC=true
SIGNAL_THROTTLE_MICROBOOST_GAP_SPLIT_ENABLED=true
PAIR_PRIORITY_TIER_ENGINE_ENABLED=false
```

## Canary sequence

### Stage 1 — Documentation and tests

```text
No runtime behavior change.
Add contract docs.
Add synthetic tests.
```

### Stage 2 — Pure ledger diagnostic

```text
Emit [PurePressureLedger].
No SignalWatch changes.
No SignalJSON changes.
```

### Stage 3 — Fusion diagnostic

```text
Emit [SignalThrottleFusionV3].
Output only PURE_RADAR_ONLY / NO_TRADE_REASONED diagnostics.
No execution path change.
```

### Stage 4 — Pair tier advisory

```text
Emit [PairPriorityTier].
Inject advisory tier into L9/synthesis.
Do not change L12.
```

### Stage 5 — Watch integration

```text
Allow non-executable SignalWatch payloads from Fusion when lineage is valid.
final_direction remains WAIT.
valid_for_execution remains false.
```

### Stage 6 — Decision integration

```text
Allow SignalDecisionUpdateJSON for terminal non-execution states.
No final execution readiness from Fusion.
```

### Stage 7 — Execution consideration

Only after repeated canary exports prove no safety regression.

Execution remains governed by:

```text
L12
SignalJsonGateAdapter
signal_execution_gates.py
RR gate
structure target gate
spread/news gate
pattern permission gate
live RR gate
no-chase gate
source lineage / lifecycle constraints
```

## Canary success metrics

```text
SignalJSON count does not unexpectedly increase.
Fusion emits no valid_for_execution=true.
Pure same-symbol huge-gap blocks remain intact.
Microboost output remains direction UNRESOLVED.
Watch/Decision outputs are explainable and non-executable.
Pair tier improves analysis priority visibility.
Existing SignalJSON gate tests remain green.
Existing UniverseRanking tests remain green.
```

## Hard rollback conditions

Immediately disable runtime Fusion flags if any of these occur:

```text
Fusion output emits valid_for_execution=true.
SignalJSON count rises without L12/gate explanation.
Pure ledger starts splitting by time gap.
Microboost resolves final direction.
Pair Tier changes L12 verdict behavior.
Watch emits without source_clean_block_id.
M15 close becomes universal for radar-only states.
```

## Bias guardrails

```text
Do not optimize for more signals.
Optimize for clearer pressure visibility and safer lifecycle explanation.
Do not convert radar into execution.
Do not loosen existing final barrier gates.
Do not let documentation-only contract be bypassed in code review.
```