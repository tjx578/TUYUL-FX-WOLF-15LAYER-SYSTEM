# Strategy 5S-CR SSOT v3.1: Amendment A3 — ExecutionBox Authority Clarification

```yaml
amendment_id: WOLF15-5SCR-SSOT-V3.1-A3
status: DRAFT_NOT_APPROVED
content_review:
  decided_by: OWNER
  decided_on: 2026-09-22
  content_status: APPROVED_WITH_AMENDMENTS_PENDING_BYTE_RATIFICATION
  predecessor_draft_sha256: c9243308158f738fb643b6a84c9ebb325cb1a7edceee869512ef9dfbb93f6dfb
  predecessor_draft_blob_id: ae26705c8a2ae23dc4297922b3efdb6fd3d1c478
  entries_content_approved: [A3-01, A3-02, A3-03, A3-04, A3-05, A3-06, A3-07, A3-08, A3-10]
  entries_content_approved_with_clarification: [A3-09]
  routes_spec_approved: [BREAK_RETEST, BREAKOUT_ACCEPTANCE]
  questions_resolved: [Q-R1, Q-R2, Q-R3, Q-R4, Q-R5]
base_ssot:
  document_id: WOLF15-5SCR-SSOT-V3.1-CANDIDATE
  path: docs/remediation/2026-09-09/source-binding/selected-ssot-v3.1.md
  sha256: 6daea387745ffa305d3cd55b0fee4f0efed79be21e24503c2a1f8a16c6a83902
  document_bytes_modified: false
companion_authority:
  document_id: WOLF15-5SCR-FINAL-AUDIT-REPLAY-WORKFLOW-V3
  location: outside the repository (owner archive)
  sha256: 4420a32f981f18e9fcd9f0cd3f8aa22362216baf4fff241ab4d6700bbee2b172
  document_bytes_modified: false
builds_on:
  A1: {sha256: 1fed7f7b2eb79152ba8f825faca4af3eed131f69222860c6793a42eabd152d40, entries_used: [A1-09, A1-10, A1-11, A1-12]}
  A2: {sha256: 9cf9e5318aa69d8ec4455b48588a924be97b7fdeaf9091e67ff90920e68236d2, entries_used: [A2-01, A2-07]}
scope: EXECUTION_BOX_ONLY
effective_authority_model: BASE_SSOT_PLUS_EXPLICIT_AMENDMENTS
dual_authority: false
runtime_activation: EXPLICIT_ONLY
final_approver: OWNER
```

## 1. Why A3 is separate

A1 carries PressureRange authority, A2 carries StructuralTarget authority. The ExecutionBox is a third object
with a different evidence class, so it gets its own artifact. A3 does not widen, reopen or reinterpret any A1 or
A2 entry; where it relies on one, it cites it.

```text
EFFECTIVE STRATEGY AUTHORITY (box scope)
= SSOT v3.1 (6daea387…) + Audit/Replay v3 (4420a32f…) where cited + A1 + A2 + this amendment
```

A3 grants **no** runtime activation and does not modify any base document. Entry types are the same as A1/A2:
`CONFLICT_OVERRIDE` (contradicts and replaces a clause) and `GAP_FILL` (the authority is silent).

**Specification approval is not runtime approval.** Every entry here may be ratified as specification while
`runtime_activation` stays `EXPLICIT_ONLY`. Every route policy that A3 introduces must additionally complete
replay and shadow evidence, and OOS evidence before canonical runtime activation (owner D2, 2026-09-21).

Source: the 12C audit (`GAP12C_EXECUTION_BOX_AUDIT_AND_DESIGN.md`) and owner decisions D1–D7 (2026-09-21).

Out of scope, and not decided anywhere in A3: `CONSUMED` trigger, `EXPIRED` trigger, structural SL, TP1, RR, the
T10 gross/net RR relation, broker adaptation, risk, execution command, child/campaign.

## 2. Entries

### A3-01 · CONFLICT_OVERRIDE · Target-first precedence also governs Audit/Replay v3

- **Source:** 12C audit, third finding.
- **Base clauses:** Audit/Replay v3 §8; SSOT §17.1.
- **Base behavior:** Audit/Replay v3 §8 lists `BUILD/REVISE/FREEZE ROUTE-SPECIFIC BOX → SELECT NEAREST FRESH
  TARGET`, the same box-before-target order as SSOT §5/§28. A2-01 resolved that conflict, but its base clauses
  name SSOT only.
- **Amended behavior:** A2-01's precedence applies to Audit/Replay v3 as well. Wherever an Audit/Replay v3
  summary orders the box before the target, **SSOT §17.1 controls**: structural target selection precedes
  route-specific ExecutionBox materialization. `RouteEvaluation` is not moved.
- **shadow_required:** false · **replay_required:** false · **oos_required:** false · **runtime_activation:** EXPLICIT_ONLY.

### A3-02 · GAP_FILL · M1 is box evidence, never box-freeze authority

- **Source:** 12C audit, second finding; owner D1.
- **Base clauses:** Audit/Replay v3 §13.1, §17.4; SSOT §16.1.
- **Base behavior:** Audit/Replay v3 line 55 binds M1/tick to pressure range, entry timing, fill path and MAE/MFE
  (no box), while its §13.1 table names M1/tick as "box evidence". §17.4 says freeze is decided by route registry
  and closed-candle authority without naming a timeframe.
- **Amended behavior:** both lines are read together as follows.

  ```text
  M1/tick MAY contribute:
    PressureRange evidence · ExecutionBox evidence · entry timing · fill/path observation · MAE/MFE / replay

  M1/tick MUST NOT independently:
    create a canonical ExecutionBox · freeze a canonical ExecutionBox · determine route policy
  ```

  **Freeze authority = an approved route policy (A3-03) + the closed-candle authority that policy names.**
  Evidence is not authority. No route policy may name M1 as its freeze timeframe unless a later amendment says so.
- **shadow_required:** false · **replay_required:** false · **oos_required:** false · **runtime_activation:** EXPLICIT_ONLY.

### A3-03 · GAP_FILL · Route policy contract

- **Source:** 12C audit, headline finding; owner D2.
- **Base clauses:** SSOT §16.1, §16.4; Audit/Replay v3 §17.3, §17.4.
- **Base behavior:** the box is "route-specific legal entry geometry" and freeze is "route registry + closed-candle
  authority", but the route registry that exists (`LocationRoutePolicyV31`) carries only route, direction,
  location alignment and quote requirement. No route has an executable interval or freeze rule.
- **Amended behavior:** a route policy is canonical only if **every** field below is defined:

  ```text
  route                              one value of the canonical route vocabulary (A3-04)
  box_policy_id, box_policy_version  canonical policy identity (A3-08)
  eligible_proof_forms               exact proof class + completion kind(s) the policy accepts
  closed_candle_authority            timeframe(s) whose closed candles the policy reads
  source_evidence_requirements       which closed candles, by role, must be present
  building_predicate                 when the box record is created
  box_low_derivation, box_high_derivation
  frozen_predicate, freeze_reason
  invalidation_basis
  future_evidence_prohibition        every input closed and observed at or before decision_time
  ```

  **A policy with any field undefined is `NOT_CANONICALLY_IMPLEMENTABLE`, and a route without a canonical policy
  produces no canonical box.** There is no fallback to M1, to `ExecutionBoxV1`, to the v2 "first M15 after the
  last event" rule, or to any generic interval. The historical v2 freeze fallback may exist only as a separately
  versioned policy compared through sensitivity replay (Audit/Replay v3 §17.4, §31), never as the canonical rule.
  Route policy content is strategy governance: an implementer may not choose it.
- **shadow_required:** true · **replay_required:** true · **oos_required:** true · **runtime_activation:** EXPLICIT_ONLY.

### A3-04 · GAP_FILL · Canonical route vocabulary and rollout status

- **Source:** owner D3.
- **Base clauses:** SSOT §16.4; Audit/Replay v3 §17.3.
- **Base behavior:** six routes are named in prose; route labels in code are free strings.
- **Amended behavior — closed vocabulary and three independent status axes:**

  ```text
  spec_status     : SPEC_DEFINED | NOT_YET_DEFINED
  evidence_status : EVIDENCE_PENDING | EVIDENCE_COMPLETE
  runtime_status  : RUNTIME_DISABLED | RUNTIME_ELIGIBLE
  ```

  | Canonical route | §16.4 relation | Proof form available today | spec | evidence | runtime |
  |---|---|---|---|---|---|
  | `BREAK_RETEST` | boundary/retest interval | CONTINUATION + `RETEST` | SPEC_DEFINED (A3-R1) | EVIDENCE_PENDING | RUNTIME_DISABLED |
  | `BREAKOUT_ACCEPTANCE` | acceptance interval outside the origin range | CONTINUATION + `ACCEPTANCE` | SPEC_DEFINED (A3-R2, acceptance-side guard) | EVIDENCE_PENDING | RUNTIME_DISABLED |
  | `PULLBACK_CONTINUATION` | structural/retest interval inside or at the edge | none that identifies a pullback structure | NOT_YET_DEFINED | EVIDENCE_PENDING | RUNTIME_DISABLED |
  | `FAILED_BREAKOUT_SELL` | failed-reclaim/rejection interval | none (counter-pressure proof, §15.3, not built) | NOT_YET_DEFINED | EVIDENCE_PENDING | RUNTIME_DISABLED |
  | `FAILED_BREAKDOWN_BUY` | reclaim/retest interval | none (counter-pressure proof, §15.3, not built) | NOT_YET_DEFINED | EVIDENCE_PENDING | RUNTIME_DISABLED |
  | `RANGE_FADE` | extreme/rejection interval | none | NOT_YET_DEFINED | EVIDENCE_PENDING | RUNTIME_DISABLED |

  - `FAILED_RECLAIM` is a completion kind of the CONTINUATION proof, **not** a route. Mapping it to
    `FAILED_BREAKDOWN_BUY` / `FAILED_BREAKOUT_SELL` would treat a continuation proof as a counter-pressure proof.
    **It stays UNMAPPED (Q-R4):** `CONTINUATION + FAILED_RECLAIM` is a valid proof outcome that yields no canonical
    ExecutionBox route in this increment. There is no fallback `FAILED_RECLAIM → BREAK_RETEST` and no implicit
    counter-route; a route for it needs a later amendment.
  - A route becomes `RUNTIME_ELIGIBLE` only after `SPEC_DEFINED` is ratified, replay + shadow + OOS evidence is
    complete, and the owner authorizes runtime activation separately. **A3 approval turns no route on.**
- **shadow_required:** true · **replay_required:** true · **oos_required:** true · **runtime_activation:** EXPLICIT_ONLY.

### A3-05 · GAP_FILL · Canonical price representation for box bounds

- **Source:** owner D4.
- **Base clauses:** SSOT §11.1, §16.1.
- **Base behavior:** proof levels (`StructuralLevelEvidenceV31.level`) and closed-candle prices are `float`; no
  clause fixes how a box bound is represented.
- **Amended behavior:**
  - Canonical `box_low` and `box_high` use the existing canonical strategy price type (`Price`: Decimal,
    max 28 digits, 12 decimal places, > 0). **No new precision is introduced for the box.**
  - Legacy float evidence is `LEGACY_EVIDENCE_REQUIRES_CANONICALIZATION`, not an authority failure. It crosses
    the boundary once, deterministically, by the repository's existing convention: `Decimal(str(value))` —
    the shortest round-trip decimal of the published value, not the binary floating-point artifact. A value that
    does not fit `Price` is rejected, never rounded or quantized.
  - For hashing, a canonical price is written as a fixed-point decimal string with no exponent and no trailing
    zeros, so `1.1000` and `1.1` hash identically.
  - **Forbidden:** float arithmetic feeding `material_box_hash`; float equality deciding a box version; broker
    `tick_size` quantization inside strategy geometry.
- **shadow_required:** false · **replay_required:** true · **oos_required:** false · **runtime_activation:** EXPLICIT_ONLY.

### A3-06 · GAP_FILL · PressureRange effect on the box

- **Source:** 12C audit point 7; owner D5.
- **Base clauses:** SSOT §16.3; A1-12.
- **Base behavior:** A1-12's matrix says `MATERIAL_RANGE_CHANGE` affects the box "once 12C exists", while §16.3's
  closed cause list does not name PressureRange.
- **Amended behavior:**

  ```text
  PressureRange change (any A1-12 class except no-class)
  → box derivation re-evaluation is REQUIRED

  PressureRange change alone
  → does NOT force a box_version increment

  box_version increments only if the approved box material projection (A3-09) changes
  ```

  `pressure_range_id` is carried as a lineage input, never as a material field by itself. Upstream truth changing
  does not mean downstream material changed.
- **shadow_required:** false · **replay_required:** true · **oos_required:** false · **runtime_activation:** EXPLICIT_ONLY.

### A3-07 · GAP_FILL · StructuralTarget revision facts → box re-evaluation obligation

- **Source:** 12C audit point 6; A2-07 left the mapping to 12C.
- **Base clauses:** SSOT §16.3.
- **Base behavior:** §16.3 names "target/invalidation revision" as a cause of box change; A2-07 supplies four
  target-side facts and explicitly defines no box reaction.
- **Amended behavior — obligation only, never a direct state mapping:**

  | A2-07 fact | `requires_box_reevaluation` |
  |---|---|
  | `TARGET_UNCHANGED` | false |
  | `TARGET_MATERIAL_CHANGE` | true |
  | `TARGET_NO_LONGER_ELIGIBLE` | true |
  | `TARGET_INVALIDATED` | true |

  `resulting_box_state` is **never** mapped from a target fact. It follows only from re-derivation under the
  route policy (A3-03), the material projection (A3-09) and the SUPERSEDED/INVALIDATED rule (A3-10).
- **shadow_required:** false · **replay_required:** true · **oos_required:** false · **runtime_activation:** EXPLICIT_ONLY.

### A3-08 · GAP_FILL · Logical and revision identity

- **Source:** 12C audit point 10; owner D6.
- **Base clauses:** SSOT §4.1, §4.2, §17.7.
- **Base behavior:** §4.1 names `execution_box_id + box_version`; nothing fixes the tuple.
- **Amended behavior:**

  ```text
  execution_box_id = UUIDv5(V31_EXECUTION_BOX_NAMESPACE,
                            [box_derivation_version, strategy_thesis_id, route, box_policy_id, box_policy_version])
  box revision     = (execution_box_id, box_version)
  ```

  - Canonical policy identity (`box_policy_id` + `box_policy_version`) is preferred over a raw implementation
    hash. A policy hash may stand in only if it is authority-defined, stable, and neither build- nor
    deployment-specific.
  - **Outside the logical id:** `pressure_range_id`, `target_id`, the ordered-proof revision, specific source
    evidence, admission class, and every clock. They are inputs, provenance or revision drivers.
  - A route change or a box-policy change creates a **new** `execution_box_id`. The same thesis + route + policy
    with changed inputs keeps the id and may append a version.
  - **Version 1** is created with the box record (A3-03 `building_predicate`). A version is appended only when
    the material projection (A3-09) changes. Versions are contiguous (no skipped numbers), append-only, never
    rewritten, and each version n > 1 records `previous_box_version = n − 1` and that version's
    `material_box_hash`. `box_sequence`, if kept, is a lifecycle-local audit ordinal with no authority.
  - **Version lock (owner, 2026-09-22):**

    ```text
    box_version starts at 1 and increments by exactly +1; no skipped versions; append-only
    same thesis + route + policy, material projection changed → same execution_box_id, box_version = previous + 1
    route or policy changed                                   → new execution_box_id, box_version = 1
    ```
- **shadow_required:** false · **replay_required:** true · **oos_required:** false · **runtime_activation:** EXPLICIT_ONLY.

### A3-09 · GAP_FILL · Material field partition and `material_box_hash`

- **Source:** 12C audit points 3–5; same discipline as A1-12.
- **Base clauses:** SSOT §15.2, §16.3; Audit/Replay v3 §13.2, §17.2.
- **Base behavior:** §16.3 lists what may and may not change a box; no field partition exists.
- **Amended behavior — proposed partition:**

  ```text
  GEOMETRY_MATERIAL  : box_low, box_high (canonical Price, A3-05)
  AUTHORITY_MATERIAL : structural_proof_id (new structural trigger / new retest interval), context_epoch_id,
                       freeze_evidence_id (canonical identity of the closed candle that satisfied the FROZEN predicate)
  LINEAGE (not hashed): pressure_range_id, target_id, A2-07 target fact, source candle ids, observed_through_utc,
                        containment sidecar
  NON_MATERIAL       : emission time, tick refresh, cluster, sticky Microboost state, transport context,
                       deployment/replica/request, publisher, telemetry count, broker quote, reference price,
                       observational timestamps, box_version itself
  ```

  ```text
  material_box_hash = canonical_sha256_v31(GEOMETRY_MATERIAL ∪ AUTHORITY_MATERIAL)
  box_version++      iff material_box_hash changes and execution_box_id is unchanged
  ```

  - **AUTHORITY_MATERIAL is material for revision semantics** (owner clarification, 2026-09-22): it is part of the
    canonical material projection and of `material_box_hash`, exactly like GEOMETRY_MATERIAL. LINEAGE is never
    hashed merely because an id changed: `pressure_range_id` and `target_id` are provenance and revision drivers,
    not box material fields.
  - **`target_id` is LINEAGE, not material.** Under the proposed route policies (A3-R1, A3-R2) the box interval
    does not read the target; the target constrains entry later, through `target_room_interval` (§17.4). A target
    revision therefore re-evaluates the box (A3-07) and versions it only if the projection moves.
  - `pressure_range_id` is LINEAGE (A3-06).
  - Each §16.3 cause maps to a partition: route change → new id (A3-08); new structural trigger / new retest
    interval → `structural_proof_id`; ContextEpoch transition → `context_epoch_id`; target/invalidation revision →
    re-evaluation (A3-07) and GEOMETRY if bounds move. The §16.3 forbidden causes are all NON_MATERIAL.
- **shadow_required:** false · **replay_required:** true · **oos_required:** false · **runtime_activation:** EXPLICIT_ONLY.

### A3-10 · GAP_FILL · SUPERSEDED vs INVALIDATED (proposed normative rule)

- **Source:** 12C audit point 9.
- **Base clauses:** SSOT §16.3, §21.6, §28.17.
- **Base behavior:** both states and both reason codes (`BOX_SUPERSEDED`, `BOX_INVALIDATED`) exist; neither is
  defined.
- **Amended behavior — proposed:**

  ```text
  SUPERSEDED  = a valid successor exists: a newer version of this box, or a new box under the same thesis
                (route or policy change), derived in the same or a later evaluation
  INVALIDATED = the box's basis is lost and NO valid successor exists
  ```

  - **Concurrent case:** when the old box loses its basis and a replacement is derived in the same re-evaluation
    transaction, the old box is `SUPERSEDED`, not `INVALIDATED`. `INVALIDATED` is reserved for "no replacement".
  - A "valid successor" is a successor whose own `building_predicate` holds; it need not be FROZEN yet.
  - `SUPERSEDED` and `INVALIDATED` are terminal; a terminal box is never resurrected.
  - Reachable transitions in the first increment: `BUILDING → FROZEN`; `BUILDING | FROZEN → SUPERSEDED |
    INVALIDATED`. `CONSUMED` has no producer; `EXPIRED` stays `RESERVED_UNREACHABLE_UNTIL_AUTHORITY_DEFINED`.
- **shadow_required:** true · **replay_required:** true · **oos_required:** false · **runtime_activation:** EXPLICIT_ONLY.

## 3. Route policies (spec content approved 2026-09-22; strategy governance decided)

Notation from the existing proof machinery (#497, `StructuralProofEvidenceV31`): H1 anchor + confirmation;
M15 **reference R**, **break B**, **completion C**; boundary **L = R.high for BUY, R.low for SELL** (the existing
`m15_level`). Every price passes A3-05 before use. `canon(x)` = A3-05 canonicalization.

Common to both policies (Q-R1, Q-R3, Q-R5):

```text
building_predicate : active DirectionalThesis · completed structural proof of the eligible form ·
                     route permitted by the thesis's ContextRouteEvaluation · canonical StructuralTarget
                     selection status SELECTED for the thesis (A2-01) ·
                     PressureRange.structural_authority == true
same-close transition : BUILDING has no minimum dwell time. BUILDING and FROZEN may share one authority time
                     when the completion close satisfies both predicates; the transition is ordered and its
                     event ordering is deterministic. No artificial extra candle is required.
post-freeze invalidation (not SL):
  BUY  : after FROZEN, an authoritative closed M15 candle with close < L invalidates the route/box basis
  SELL : after FROZEN, an authoritative closed M15 candle with close > L invalidates the route/box basis
  close == L does not invalidate
upstream invalidation : thesis or proof invalidated without successor, route blocked by the current route
                     evaluation, or no eligible canonical target
resulting state      : decided only by A3-10 (SUPERSEDED if a valid successor exists, else INVALIDATED)
```

- **`PressureRange.structural_authority == true` is an ExecutionBox formation prerequisite, not a StructuralTarget
  predicate.** Target eligibility stays exactly A2-05's six predicates. Under the current A1 contract only
  `COMPLETE` coverage carries structural authority, so `MISSING`, `PARTIAL` or `QUARANTINED` ranges yield
  **no canonical BUILDING box**, with no downgrade and no fallback to M1.
- **Box invalidation ≠ broker stop ≠ risk SL ≠ order stop level.** The closed-candle reclaim failure against L is a
  route-validity event only; structural SL (§17.5) remains the geometry step after the box.

### A3-R1 · `BREAK_RETEST` · box policy `5scr.box-policy.break-retest` v1

```text
eligible_proof_forms     : proof_class CONTINUATION, m15_completion_kind RETEST, pattern route BREAK_RETEST
closed_candle_authority  : H1 (structure proof), M15 (break, completion, freeze). M1: evidence only.
source_evidence          : R, B, C as closed, authoritative M15 candles of the proof
building_predicate       : common (above)
BUY  box                 : box_low = canon(C.low), box_high = canon(L)          (RETEST ⇒ C.low ≤ L)
SELL box                 : box_low = canon(L),     box_high = canon(C.high)     (RETEST ⇒ C.high ≥ L)
frozen_predicate         : C closed at or before decision_time · box_low ≤ box_high · every input closed and
                           observed at or before decision_time
freeze_reason            : M15_RETEST_COMPLETION_CLOSED
invalidation_basis       : common post-freeze invalidation + upstream invalidation (above)
```

### A3-R2 · `BREAKOUT_ACCEPTANCE` · box policy `5scr.box-policy.breakout-acceptance` v1

```text
eligible_proof_forms     : proof_class CONTINUATION, m15_completion_kind ACCEPTANCE, pattern route BREAKOUT_ACCEPTANCE
closed_candle_authority  : as A3-R1
source_evidence          : as A3-R1
building_predicate       : common (above)
acceptance_side_guard    : BUY requires C.low > L · SELL requires C.high < L (strict, so the interval is never
                           degenerate)
BUY  box                 : box_low = canon(L),      box_high = canon(C.low)
SELL box                 : box_low = canon(C.high), box_high = canon(L)
frozen_predicate         : acceptance_side_guard holds · otherwise as A3-R1
freeze_reason            : M15_ACCEPTANCE_COMPLETION_CLOSED
invalidation_basis       : common post-freeze invalidation + upstream invalidation (above)
```

- The interval lies entirely outside the origin range (beyond L), matching §16.4's "acceptance interval di luar
  origin range". The full acceptance candle range `[C.low, C.high]` is **not** the box.
- **If the acceptance-side guard fails, A3-R2 MUST NOT FREEZE A BOX.** There is no fallback to `[C.low, C.high]`
  and no generic interval.
- Non-normative note: the existing completion classifier labels a candle `ACCEPTANCE` only when it neither
  retested nor failed-reclaimed, which implies the guard today. The guard is stated anyway so that the policy never
  depends on that implementation detail.

### Resolved questions (owner, 2026-09-22)

```text
Q-R1  CLOSED — same-close BUILDING → FROZEN transition allowed; no minimum dwell time; no extra M15 candle.
Q-R2  CLOSED — BREAKOUT_ACCEPTANCE box = [L, C.low] (BUY) / [C.high, L] (SELL) under the strict acceptance-side
      guard; never the full acceptance candle.
Q-R3  CLOSED — define box invalidation in A3: post-freeze authoritative M15 close beyond L (BUY < L, SELL > L);
      equality does not invalidate; not SL. New strategy behavior: replay + shadow, OOS before runtime.
Q-R4  CLOSED — FAILED_RECLAIM stays UNMAPPED.
Q-R5  CLOSED — canonical BUILDING requires PressureRange.structural_authority == true; box prerequisite, not a
      seventh target predicate.
```

## 4. Approval

**Not approved as exact bytes.** The owner approved the content on 2026-09-22 (A3-01 … A3-08 and A3-10 approved,
A3-09 approved with clarification, A3-R1 and A3-R2 spec approved, Q-R1 … Q-R5 resolved) and required these
decisions to be encoded before byte ratification. This document is the successor of the draft bytes
`sha256 c9243308…93f6dfb` (git blob `ae26705c…c478`), pinned in `content_review`. A3 becomes approved only by a
separate owner ratification of the exact bytes of this document.

Approval grants no runtime activation and no implementation authority:

```text
A3 APPROVED  ≠  ExecutionBoxV31 implementation authorized
A3 APPROVED  ≠  any route RUNTIME_ELIGIBLE
```

`grants_runtime_activation` stays `false`; every entry keeps `runtime_activation: EXPLICIT_ONLY`. A route becomes
`RUNTIME_ELIGIBLE` only after replay, shadow and OOS evidence pass and the owner authorizes activation separately.
