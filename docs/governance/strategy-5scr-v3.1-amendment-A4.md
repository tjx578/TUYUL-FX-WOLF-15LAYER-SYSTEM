# Strategy 5S-CR SSOT v3.1: Amendment A4 — Structural Geometry Authority

```yaml
amendment_id: WOLF15-5SCR-SSOT-V3.1-A4
status: APPROVED_PER_ENTRY
ratification:
  ratified_draft_sha256: 3afd4339f3c4d330aa12af5b16da98dbfba6b54fade0a517bb3f3f9d0d48ff02
  ratified_draft_blob_id: f84aa6079ccf0603c74152094358e8f59808f2c0
  ratified_on: 2026-09-27
  ratified_by: OWNER
  method: independent byte verification by the owner against the GitHub head (sha256 + git blob + 22334 bytes), PR #511 head 2564a581 CI 40/40 + Security Gate PASS
  approved_entries: [A4-01, A4-02, A4-03, A4-04, A4-05, A4-06, A4-07, A4-08, A4-09, A4-10, A4-11, A4-12, A4-13, A4-14, A4-15, A4-16]
  approved_geometry_policies: [A4-G1 BREAK_RETEST, A4-G2 BREAKOUT_ACCEPTANCE]
  pending_entries: []
  ratified_normative_span_sha256: 0eb2788b923ac5fdc3e22d646d9ca765ad20b16da3c235bdd610d885b1afa780
content_review:
  decided_by: OWNER
  decided_on: 2026-09-27
  content_status: APPROVED_PENDING_BYTE_RATIFICATION
  predecessor_draft_sha256: ab5ceb24012d7bfa87f942a2cb49b981f5a6bbc95f28a7203c950e089bec9a44
  predecessor_draft_blob_id: 0ad47194b52f56fcc33f530ec4957acbd5a7e4fd
  questions_resolved: [Q-A4-1, Q-A4-2, Q-A4-3, Q-A4-4]
content_source:
  decided_by: OWNER
  decided_on: 2026-09-22
  decisions: [OD-1, OD-2, OD-3, OD-4, OD-5, OD-6, OD-7, OD-8, OD-9, OD-10, OD-11, OD-12, OD-13, OD-14, OD-15, OD-16]
  audit: GAP12D_STRUCTURAL_GEOMETRY_AUDIT.md (12D, Lane B)
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
  A1: {sha256: 1fed7f7b2eb79152ba8f825faca4af3eed131f69222860c6793a42eabd152d40, entries_used: []}
  A2: {sha256: 9cf9e5318aa69d8ec4455b48588a924be97b7fdeaf9091e67ff90920e68236d2, entries_used: [A2-01, A2-02, A2-05, A2-07]}
  A3: {sha256: 538b3b6f58513bda10d9f7b49f2665c9178d91ff290d1cc811d56130bf7294cf, entries_used: [A3-05, A3-07, A3-08, A3-09, A3-10, A3-R1, A3-R2]}
scope: STRUCTURAL_GEOMETRY_ONLY
effective_authority_model: BASE_SSOT_PLUS_EXPLICIT_AMENDMENTS
dual_authority: false
runtime_activation: EXPLICIT_ONLY
final_approver: OWNER
```

## 1. Why A4 is separate

A1 carries PressureRange authority, A2 StructuralTarget authority, A3 ExecutionBox authority. Structural
geometry (entry reference, structural SL, TP1, gross RR) is a fourth object downstream of the frozen box, so it
gets its own artifact (OD-16). A4 does not widen, reopen or reinterpret any A1, A2 or A3 entry; where it relies on
one, it cites it.

```text
EFFECTIVE STRATEGY AUTHORITY (geometry scope)
= SSOT v3.1 (6daea387…) + Audit/Replay v3 (4420a32f…) where cited + A1 + A2 + A3 + this amendment
```

A4 grants **no** runtime activation and does not modify any base document. Entry types are the same as A1–A3:
`CONFLICT_OVERRIDE` (contradicts and replaces a clause) and `GAP_FILL` (the authority is silent).

**Specification approval is not runtime approval.** Every entry may be ratified as specification while
`runtime_activation` stays `EXPLICIT_ONLY`. Evidence flags follow the owner matrix (Q-A4-4): OOS only for market or
numeric semantics that can change a setup outcome; shadow for behavior that must be shown on natural market
progression; replay for deterministic lineage and geometry behavior that must reproduce.

Source: the 12D audit (`GAP12D_STRUCTURAL_GEOMETRY_AUDIT.md`) and owner decisions OD-1 … OD-16 (2026-09-22).

Position in the chain (A2-01 order, unchanged):

```text
canonical StructuralTarget selection (A2) → ExecutionBoxV31 FROZEN (A3) → StructuralGeometry (A4)
→ Broker/Cost Adaptation (G4, not A4) → net RR → TradePlanCandidate (non-executable)
```

Out of scope, and not decided anywhere in A4: order type, actual order price, broker adaptation (bid/ask, spread,
drift, tick size, tick value, stops level, freeze level, volume, margin), cost model, net RR computation, economic
minimum distance, broker SL trigger semantics, thesis invalidation (A1-07), risk, execution command,
child/campaign.

## 2. Entries

### A4-01 · GAP_FILL · Structural SL anchor

- **Owner decision:** OD-1.
- **Base clauses:** SSOT §17.5, §17.1; Audit/Replay v3 §20.1.
- **Base behavior:** §17.5 says BUY stop below and SELL stop above "structural invalidation" but never names the
  price. A3 separates box invalidation from SL and leaves SL out of scope.
- **Amended behavior:** for both approved routes (A3-R1 `BREAK_RETEST`, A3-R2 `BREAKOUT_ACCEPTANCE`):

```text
BUY  : structural_sl_anchor = canon(R.low)
SELL : structural_sl_anchor = canon(R.high)
R    = the canonical M15 reference candle of the ordered structural proof (A3 §3 notation)
canon = A3-05 canonicalization (Decimal(str(x)) into Price; reject, never round)
```

- This is a **new A4 policy**, not a claim that the SSOT already fixed this level.
- **shadow_required:** true · **replay_required:** true · **oos_required:** true · **runtime_activation:** EXPLICIT_ONLY.

### A4-02 · GAP_FILL · No strategy-side SL buffer

- **Owner decision:** OD-2.
- **Base clauses:** SSOT §17.5; Audit/Replay v3 §20.1.
- **Base behavior:** §17.5 requires a versioned noise/spread buffer and names no value; the only code buffer is one
  broker tick (`P5_ROUTE_EXTREME_1_TICK_V1`, v2).
- **Amended behavior:** the versioned geometry policy (A4-14) carries buffer = NONE:

```text
structural_sl = structural_sl_anchor
```

  Forbidden inside A4 geometry: ±1 tick · ±N pip · ATR · spread multiple · metal $ offset.
- Broker feasibility may later **reject** the canonical SL; it may never move it silently.
- **shadow_required:** true · **replay_required:** true · **oos_required:** true · **runtime_activation:** EXPLICIT_ONLY.

### A4-03 · GAP_FILL · Gross RR is calculated, never a minimum (T10)

- **Owner decision:** OD-3.
- **Base clauses:** SSOT §17.4, §17.3, §17.6; Audit/Replay v3 §19, §20.2.
- **Base behavior:** §17.4 uses a "minimum RR R before cost" with no value; §17.3 carries only
  `minimum_net_rr: 1.5`; A2 annex item 4 records the gross/net relation as not defined.
- **Amended behavior:**

```text
gross_rr          = CALCULATED (A4-11)
gross_rr_minimum  = NONE
minimum_net_rr    = 1.5 (existing SSOT §17.3 authority, unchanged)
net_rr            = computed AFTER broker/cost adaptation, never by A4
```

  Flow: StructuralGeometry → gross RR observation → Broker/Cost Adaptation → net RR → net RR ≥ 1.5.
- A historical gross threshold of 2.0 is `LEGACY / NOT_CANONICAL_AUTHORITY`. A4 creates no gross threshold.
- **shadow_required:** true · **replay_required:** true · **oos_required:** true · **runtime_activation:** EXPLICIT_ONLY.

### A4-04 · CONFLICT_OVERRIDE · No minimum target distance in strategy geometry

- **Owner decision:** OD-4.
- **Base clauses:** SSOT §17.3, §23.14, §21.6; Audit/Replay v3 §20.2.
- **Base behavior:** §17.3 carries `minimum_structural_target_pips: 10`; §23.14 rejects a nearest target below that
  floor (`NO_TRADE_TARGET_BELOW_EXECUTION_FLOOR`). Audit/Replay v3 §20.2 treats 6 pip FX / $5 XAU as hypotheses.
- **Amended behavior:** canonical strategy geometry has **no** minimum reward floor:

```text
10-pip floor = NONE
```

  Not part of A4: FX minimum target 10 pip · metal $5 floor · any instrument minimum reward floor.
- If a minimum economic distance is needed later, it belongs to G4 / broker-execution feasibility, never to target
  or strategy geometry. A4 does not reopen A2-05: a failing setup is rejected, never re-targeted to a farther target.
- **shadow_required:** true · **replay_required:** true · **oos_required:** true · **runtime_activation:** EXPLICIT_ONLY.

### A4-05 · GAP_FILL · Entry interval and RR reference entry; no order type

- **Owner decision:** OD-5.
- **Base clauses:** SSOT §17.1, §17.7; Audit/Replay v3 §19.
- **Base behavior:** §17.1 step 9 names "candidate entry and order type" with no rule; code picks the worst-price
  feasible edge without authority.
- **Amended behavior:** A4 does **not** choose an order type.

```text
entry_interval      = [box_low, box_high] of the FROZEN ExecutionBox revision
BUY  rr_reference_entry = box_high
SELL rr_reference_entry = box_low
```

  `rr_reference_entry` is the worst-case strategy entry inside the interval, used only for the conservative gross RR.
  It is **not** an actual order price, a market order, a limit order or a stop order. Order type and order price
  belong to G4.
- **shadow_required:** true · **replay_required:** true · **oos_required:** true · **runtime_activation:** EXPLICIT_ONLY.

### A4-06 · GAP_FILL · Entry interval identity is the box revision

- **Owner decision:** OD-6.
- **Base clauses:** SSOT §17.4, §4.1.
- **Base behavior:** §17.4 names `structural_entry_interval` and `route_entry_interval`; A3 produces one box.
- **Amended behavior:** both intervals are the frozen ExecutionBox interval, and the entry interval has no identity
  of its own:

```text
entry interval identity = (execution_box_id, box_version)
```

  No `entry_interval_id` is created. When the box revision changes, the entry interval revision changes with it.
- **shadow_required:** false · **replay_required:** true · **oos_required:** false · **runtime_activation:** EXPLICIT_ONLY.

### A4-07 · CONFLICT_OVERRIDE · Broker boundary

- **Owner decision:** OD-7.
- **Base clauses:** SSOT §17.4, §17.1, §11.1; Audit/Replay v3 §4.2.
- **Base behavior:** SSOT §17.4 places `broker_constraint_interval` inside Strategy Core; Audit/Replay v3 §4.2 places
  tick size and stop/freeze level in Replay B; A3-05 forbids tick quantization for the box.
- **Amended behavior:** the separation is fixed as follows.

```text
A4 / Strategy : canonical Decimal entry interval · canonical SL · canonical TP1 · gross RR
G4 / Broker   : bid/ask · spread · drift · tick size · tick value · stops level · freeze level ·
                order price · volume · margin
```

  `broker_constraint_interval` is not evaluated in A4. The A3-05 prohibition extends from the box to SL, TP1 and
  the entry reference: **no tick-size quantization in A4.**
- **Executable order placement is restricted in G4, never in A4 (Q-A4-1).** G4 forms the executable entry domain
  from the unclamped A4 geometry and then intersects it with broker constraints:

```text
BUY  : ExecutionBox ∩ (structural_sl, TP1) ∩ broker constraints
SELL : ExecutionBox ∩ (TP1, structural_sl) ∩ broker constraints
empty intersection → NO EXECUTABLE ENTRY
```

  An empty domain never moves the SL, moves TP1, expands the box or selects a farther target. **A4 geometry
  remains immutable.**
- **shadow_required:** false · **replay_required:** true · **oos_required:** false · **runtime_activation:** EXPLICIT_ONLY.

### A4-08 · GAP_FILL · No cost model in A4

- **Owner decision:** OD-8.
- **Base clauses:** SSOT §17.6; Audit/Replay v3 §20.2.
- **Base behavior:** §17.6 defines net RR after spread, commission, slippage and swap, naming no source or
  validity; code carries a `5 × spread` cost floor with no authority.
- **Amended behavior:** net RR authority belongs to downstream Broker/Cost Adaptation. A4 only supplies the
  canonical geometry that computation needs. A4 must not read live spread · commission · swap · slippage
  assumptions. A cost model, when defined, must be versioned and deterministic, in G4.
- **shadow_required:** false · **replay_required:** false · **oos_required:** false · **runtime_activation:** EXPLICIT_ONLY.

### A4-09 · GAP_FILL · TP1 is the selected target price, exactly

- **Owner decision:** OD-9.
- **Base clauses:** SSOT §17.2, §17.7.
- **Base behavior:** no clause says whether TP1 equals the target price or carries an offset.
- **Amended behavior:**

```text
TP1 = selected StructuralTarget.price   (A2-05 selection, status SELECTED)
```

  Forbidden: TP1 ± ticks · TP1 ± spread · TP1 haircut · farther target selection. If the target is not
  economically feasible, the setup fails downstream; TP1 is never moved.
- **shadow_required:** true · **replay_required:** true · **oos_required:** true · **runtime_activation:** EXPLICIT_ONLY.

### A4-10 · GAP_FILL · Three revision domains and the geometry material projection

- **Owner decision:** OD-10.
- **Base clauses:** SSOT §4.1, §4.2, §15.1, §16.3, §17.7.
- **Base behavior:** A3-09 makes `target_id` box lineage, so a target change can leave `box_version` unchanged while
  TP1 and RR change. No authority defines geometry or tradeplan revision.
- **Amended behavior:** three separate revision domains:

```text
ExecutionBox revision  ≠  StructuralGeometry revision  ≠  TradePlanCandidate revision
```

  No new logical `structural_geometry_id` is created for the first demo. StructuralGeometry is identified by a
  deterministic material projection:

```text
GEOMETRY_MATERIAL : box revision (execution_box_id, box_version) · structural_sl_anchor · structural_sl ·
                    TP1 target material (target_id, tp1) · rr_reference_entry ·
                    geometry policy (geometry_policy_id, geometry_policy_version)
material_geometry_hash = canonical sha256 of GEOMETRY_MATERIAL, prices as A3-05 decimal text
```

  If the projection changes: StructuralGeometry materially changed → a new TradePlanCandidate material revision. It
  does **not** force `box_version` to increment. A target can change and cause a TradePlanCandidate revision while
  the box stays identical. The previous TradePlanCandidate is append-only and superseded, never mutated
  retroactively. `gross_rr` is derived from the projection and is not an extra material field.
- **shadow_required:** true · **replay_required:** true · **oos_required:** false · **runtime_activation:** EXPLICIT_ONLY.

### A4-11 · GAP_FILL · Exact numeric representation and the gross RR formula

- **Owner decision:** OD-11.
- **Base clauses:** SSOT §11.1, §17.4, §17.7.
- **Base behavior:** proof prices are float; implementations disagree on Fraction vs quantized Decimal.
- **Amended behavior:** no float. Inputs are `Price` / Decimal (A3-05); arithmetic is exact Decimal or an exact
  rational.

```text
BUY  : risk = rr_reference_entry − structural_sl   reward = TP1 − rr_reference_entry
SELL : risk = structural_sl − rr_reference_entry   reward = rr_reference_entry − TP1
gross_rr = reward / risk
required : risk > 0 and reward > 0, otherwise ROUTE_NO_VALID_ENTRY_DOMAIN
cause    : mandatory canonical field when ROUTE_NO_VALID_ENTRY_DOMAIN is emitted here:
           STRUCTURAL_RISK_NON_POSITIVE   if risk <= 0
           STRUCTURAL_REWARD_NON_POSITIVE if risk > 0 and reward <= 0
```

  The status names the category and `cause` names the specific failure (Q-A4-2); risk is evaluated first, so a
  setup failing both carries `STRUCTURAL_RISK_NON_POSITIVE`.

  `gross_rr` is serialized as an exact reduced rational (integer numerator, positive integer denominator); no binary
  float, no quantum, no rounding mode.
- **shadow_required:** true · **replay_required:** true · **oos_required:** true · **runtime_activation:** EXPLICIT_ONLY.

### A4-12 · GAP_FILL · Box invalidation, thesis invalidation and broker SL stay separate

- **Owner decision:** OD-12.
- **Base clauses:** SSOT §17.5, §12.1.
- **Base behavior:** thesis actionability (`close <= L`, float, pending A1-07) and box post-freeze invalidation
  (`close < L`, Decimal, ratified A3) disagree on equality.
- **Amended behavior:** A4 does **not** ratify A1-07 and does not try to align the pending thesis invalidation. A3
  remains authoritative for the box (BUY M15 close < L invalidates · SELL M15 close > L invalidates · close == L
  does not invalidate). For structural SL, `R.low` / `R.high` is a boundary price only; broker trigger-on-touch
  semantics are not A4 authority.

```text
box invalidation  ≠  thesis invalidation  ≠  broker SL trigger
```

- **shadow_required:** false · **replay_required:** true · **oos_required:** false · **runtime_activation:** EXPLICIT_ONLY.

### A4-13 · GAP_FILL · Closed geometry reason vocabulary

- **Owner decision:** OD-13.
- **Base clauses:** SSOT §21.6, §23.14.
- **Base behavior:** §21.6 and §23.14 disagree on floor code names; code uses free strings.
- **Amended behavior:** A4 emits only:

```text
STRUCTURAL_GEOMETRY_READY
STRUCTURAL_SL_UNAVAILABLE
STRUCTURAL_TARGET_UNAVAILABLE
ROUTE_NO_VALID_ENTRY_DOMAIN
STRUCTURAL_RISK_NON_POSITIVE
STRUCTURAL_REWARD_NON_POSITIVE
STRUCTURAL_GEOMETRY_MATERIAL_CHANGE
EXECUTION_BOX_NOT_FROZEN
GEOMETRY_POLICY_UNKNOWN
```

  `EXECUTION_BOX_NOT_FROZEN` and `GEOMETRY_POLICY_UNKNOWN` are A4 prerequisite and policy failures only, with no
  broker or risk semantics (Q-A4-3). Net RR status carried downstream: `NET_RR_NOT_EVALUATED`. A4 never emits `RR_FAIL`, `RR_BELOW_MINIMUM`,
  `COST_FLOOR_FAILED`, `TARGET_BELOW_EXECUTION_FLOOR` or any broker reason.
- **shadow_required:** false · **replay_required:** false · **oos_required:** false · **runtime_activation:** EXPLICIT_ONLY.

### A4-14 · GAP_FILL · Versioned geometry policy registry

- **Owner decision:** OD-14.
- **Base clauses:** SSOT §17.3, §16.4.
- **Base behavior:** the execution policy is env-selectable and float-valued; no geometry policy exists.
- **Amended behavior:** a versioned StructuralGeometry policy registry; selection by environment variable is
  forbidden. Each approved route refers to one approved policy identity and version; the policy fixes the SL anchor
  rule, the entry-reference rule, the TP1 rule and the gross RR calculation rule. Unknown policy: reject
  (`GEOMETRY_POLICY_UNKNOWN`). **There is no default policy.** Legacy `FX_MIN_TARGET_10P_V1`, `FX_LEGACY_6P_V1`, the
  $5 XAU floor and `FULL_CLOSE_AT_TP1` are not A4 authority.
- **shadow_required:** false · **replay_required:** true · **oos_required:** false · **runtime_activation:** EXPLICIT_ONLY.

### A4-15 · GAP_FILL · Re-evaluation and handoff rebinding

- **Owner decision:** OD-15.
- **Base clauses:** SSOT §4.2, §17.7, §19.3.
- **Base behavior:** the handoff is bound to the legacy `TargetUniverseV31`; no rule covers rebinding.
- **Amended behavior:**

```text
upstream box / target / SL material changed  → re-evaluate StructuralGeometry
resulting geometry material changed          → new TradePlanCandidate revision; old candidate stays historical
```

  Risk handoff is for the latest canonical candidate only, and every handoff references an exact TradePlanCandidate
  revision. An old risk reservation is never silently rebound to a new revision.
- **shadow_required:** true · **replay_required:** true · **oos_required:** false · **runtime_activation:** EXPLICIT_ONLY.

### A4-16 · GAP_FILL · Packaging

- **Owner decision:** OD-16.
- **Base clauses:** SSOT §17.1.
- **Base behavior:** geometry items sit across SSOT §17 with no single authority artifact.
- **Amended behavior:** A4 is a separate artifact, `v3.1-A4 Structural Geometry Authority`, not an extension of A3.
  It becomes `APPROVED_PER_ENTRY` only after owner ratification on exact bytes; `grants_runtime_activation` stays
  false. A4 approval alone opens no trading.
- **shadow_required:** false · **replay_required:** false · **oos_required:** false · **runtime_activation:** EXPLICIT_ONLY.

## 3. Geometry policies (encode OD-1 … OD-14)

Notation as A3 §3: M15 reference **R**, break **B**, completion **C**; boundary **L = R.high for BUY, R.low for
SELL**. Every price passes A3-05 before use.

Common to both policies:

```text
prerequisites  : ExecutionBox revision in state FROZEN (else EXECUTION_BOX_NOT_FROZEN) ·
                 StructuralTarget selection status SELECTED for the same thesis (else STRUCTURAL_TARGET_UNAVAILABLE) ·
                 proof_id == box material structural_proof_id · every input closed and observed at or before
                 decision_time
structural_sl  : BUY canon(R.low) · SELL canon(R.high) · buffer NONE (else STRUCTURAL_SL_UNAVAILABLE)
tp1            : selected StructuralTarget.price, no offset
entry_interval : [box_low, box_high] of the FROZEN box revision
rr_reference   : BUY box_high · SELL box_low
gross_rr       : A4-11 formula, exact; no minimum
net_rr         : NET_RR_NOT_EVALUATED
```

### A4-G1 · `BREAK_RETEST` · geometry policy `5scr.geometry-policy.break-retest` v1

```text
box policy      : 5scr.box-policy.break-retest v1 (A3-R1)
BUY             : entry_interval [canon(C.low), canon(L)] · rr_reference canon(L) · structural_sl canon(R.low)
SELL            : entry_interval [canon(L), canon(C.high)] · rr_reference canon(L) · structural_sl canon(R.high)
```

### A4-G2 · `BREAKOUT_ACCEPTANCE` · geometry policy `5scr.geometry-policy.breakout-acceptance` v1

```text
box policy      : 5scr.box-policy.breakout-acceptance v1 (A3-R2)
BUY             : entry_interval [canon(L), canon(C.low)] · rr_reference canon(C.low) · structural_sl canon(R.low)
SELL            : entry_interval [canon(C.high), canon(L)] · rr_reference canon(C.high) · structural_sl canon(R.high)
```

The other four A3 routes have no box policy and therefore no geometry policy.

Non-normative note: A4 does not re-order Audit/Replay v3 §20.2. The SL anchor comes from R and does not depend on
any entry choice, so no SL-after-entry ordering question arises inside A4.

### Resolved questions (owner, 2026-09-27)

```text
Q-A4-1  CLOSED — G4 restricts executable order placement to ExecutionBox ∩ (SL, TP1) for BUY and
        ExecutionBox ∩ (TP1, SL) for SELL, intersected with broker constraints; empty → NO EXECUTABLE ENTRY.
        A4 geometry remains immutable (A4-07).
Q-A4-2  CLOSED — status ROUTE_NO_VALID_ENTRY_DOMAIN with a mandatory canonical cause
        STRUCTURAL_RISK_NON_POSITIVE or STRUCTURAL_REWARD_NON_POSITIVE (A4-11).
Q-A4-3  CLOSED — EXECUTION_BOX_NOT_FROZEN and GEOMETRY_POLICY_UNKNOWN approved (A4-13).
Q-A4-4  CLOSED — per-entry shadow/replay/OOS flags fixed by the owner matrix (each entry above).
```

## 4. Approval

**Ratified 2026-09-27.** The owner approved the content (OD-1 … OD-16 on 2026-09-22; Q-A4-1 … Q-A4-4 on
2026-09-27, including the risk-first cause precedence of A4-11), had those decisions encoded as a successor of the
draft bytes `sha256 ab5ceb24…9a44` (git blob `0ad47194…e4fd`, pinned in `content_review`), and then independently
verified and ratified the exact bytes `sha256 3afd4339…ff02` (git blob `f84aa607…f2c0`, 22334 bytes) at PR #511
head `2564a581` (CI 40/40, Security Gate PASS). A4-01 … A4-16 and geometry policies A4-G1, A4-G2 are approved.

This document is the approved successor of those exact bytes. Only approval metadata changed: the `status` line,
the `ratification` block and this section. Sections 1–3 are byte-identical to the ratified bytes, pinned by
`ratified_normative_span_sha256` (from `## 1.` up to the start of `## 4.`).

Approval is authority and specification approval only. It grants no runtime activation:

```text
A4 APPROVED  ≠  StructuralGeometryV31 implementation authorized
A4 APPROVED  ≠  any route RUNTIME_ELIGIBLE
A4 APPROVED  ≠  net RR, broker adaptation or order type decided
```

`grants_runtime_activation` stays `false`; every entry keeps `runtime_activation: EXPLICIT_ONLY`. Implementation
authority is a separate owner decision; a route becomes `RUNTIME_ELIGIBLE` only after the evidence each entry
requires passes and the owner authorizes activation separately.
