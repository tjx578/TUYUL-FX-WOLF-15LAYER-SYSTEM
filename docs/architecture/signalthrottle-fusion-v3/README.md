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

## Implementation status legend

Use this legend inside all Fusion V3 docs and code reviews:

```text
IMPLEMENTED
= already represented in current runtime code or existing architecture.

PARTIAL
= present in runtime, but naming, adapter coverage, or emitted surfaces still need normalization.

PLANNED_CONTRACT
= approved architecture target, but runtime implementation is not complete yet.

OPTIONAL
= useful observability field, but not required to land the first safe implementation.

FORBIDDEN
= implementation must not introduce this behavior.
```

This prevents documentation from being misread as a claim that every planned field is already emitted by runtime.

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

## Current contract status map

Use this map to avoid confusing the contract target with runtime rollout state:

```text
Pure Pressure Ledger wrapper/output          = IMPLEMENTED
V1 scanner-cycle clean block ledger          = IMPLEMENTED
Pure pressure quality diagnostics            = IMPLEMENTED
Radar Context vs Execution Context split     = IMPLEMENTED
SignalThrottleFusionV3 diagnostic output     = IMPLEMENTED
Dynamic M15 close policy                     = IMPLEMENTED
Microboost pure-stage boundary              = IMPLEMENTED / must preserve
Source lineage guard                         = IMPLEMENTED / must preserve
PairPriorityTier pressure-aware adapter      = PLANNED_CONTRACT
DecisionUpdate terminal NO_TRADE_REASONED    = PARTIAL
Fusion V3 execution impact                   = FORBIDDEN unless future gated rollout approves it
Pair Tier influence on L12 / SignalJSON      = FORBIDDEN
```

## Review checklist for every future patch

Any patch touching SignalThrottle, Microboost, SignalWatch, Pair Tier, Market Context, or SignalJSON must answer:

```text
Does this preserve gap-agnostic Pure Pressure Ledger behavior?
Does this preserve scanner-cycle-aware V1 clean block behavior?
Does this keep Microboost direction UNRESOLVED?
Does this keep Watch non-executable?
Does this keep Pair Tier advisory-only?
Does this keep SignalJSON gate authority intact?
Does this avoid making M15 close universal?
Does this emit diagnostics instead of going silent?
```
