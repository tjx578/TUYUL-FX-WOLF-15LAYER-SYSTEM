# SignalThrottle Fusion V3 Documentation

Status: documentation index / implementation map.  
Scope: explains how the Fusion V3 contract should be applied across the repo without creating logic drift.

## Why this documentation exists

SignalThrottle has two separate responsibilities that must not be blended:

```text
1. Safety Clamp
   Prevent too many final execution verdicts from being emitted.

2. Pure Pressure Ledger
   Detect uninterrupted pair pressure from raw throttle/intel/canary events.
```

The system drift risk appears when those meanings are mixed. This documentation set fixes that by giving each stage a contract.

## Contract source of truth

Read this first:

```text
docs/architecture/contracts/signalthrottle-fusion-v3-contract.md
```

That file defines the non-negotiable system boundaries.

## Section documents

```text
01-raw-capture-and-pure-ledger.md
02-block-quality-and-tiering.md
03-direction-and-market-context.md
04-microboost-watch-decision.md
05-execution-firewall-and-rollout.md
06-implementation-checklist.md
```

## Layer overview

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

## Implementation philosophy

Do not rewrite working systems. Formalize boundaries.

```text
Keep SignalThrottle safety clamp as-is.
Add pure pressure ledger beside it.
Keep Microboost as burst/timing evidence.
Keep SignalWatch non-executable.
Keep Pair Tier advisory-only.
Keep SignalJSON as the final execution firewall.
```

## Production rollout rule

Fusion V3 must start as diagnostic/advisory only.

```env
SIGNAL_THROTTLE_FUSION_V3_ENABLED=false
SIGNAL_THROTTLE_FUSION_DIAGNOSTIC_ENABLED=true
SIGNAL_THROTTLE_FUSION_EXECUTION_ENABLED=false
```

The first successful rollout is not measured by more SignalJSON output. It is measured by better visibility:

```text
Pure pressure blocks visible
No silent pressure disappearance
Clean block lineage attached
Pair tier explains priority
Watch/Decision remains non-executable unless existing gates allow it
```

## Review checklist for every future patch

Any patch touching SignalThrottle, Microboost, SignalWatch, Pair Tier, Market Context, or SignalJSON must answer:

```text
Does this preserve gap-agnostic Pure Pressure Ledger behavior?
Does this keep Microboost direction UNRESOLVED?
Does this keep Watch non-executable?
Does this keep Pair Tier advisory-only?
Does this keep SignalJSON gate authority intact?
Does this avoid making M15 close universal?
Does this emit diagnostics instead of going silent?
```