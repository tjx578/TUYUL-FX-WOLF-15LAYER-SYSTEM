# Strategy 5S-CR SSOT v3.1: Amendment A2 — Structural Target Authority Clarification

```yaml
amendment_id: WOLF15-5SCR-SSOT-V3.1-A2
status: APPROVED_PER_ENTRY
ratification:
  ratified_draft_sha256: 4780c8989bfad0f6322ff3543774cc637f3e32c68d0e5747670fe18267608815
  ratified_draft_blob_id: d8433a126c689fea3ea6f859cddeacdd4a4ed1c9
  ratified_on: 2026-09-21
  ratified_by: OWNER
  method: independent byte verification by the owner (Get-FileHash + git rev-parse)
  approved_entries: [A2-01, A2-02, A2-03, A2-04, A2-05, A2-06]
  pending_entries: []
draft_revision:
  base_approved_document_sha256: 9ca93cca0f10fb2de30e858f978b2b0b4908fda5ed9eb9d9ad597990fe6165e7
  base_approved_blob_id: cf07bd46b4b54edbc0f6fa6b69b6d5a99fd34184
  approved_entries_span_sha256: cb82a987ac2b22f5c8da83348f11175676fdae92b63251bdbfc0590e2a88891f
  pending_entries: []
ratification_a2_07:
  ratified_draft_sha256: 01e9c76d71229a29a370acd023e45566329f1b7805140b4533ce7c0932253ba6
  ratified_draft_blob_id: 39d380d394c47a6701871a2c9fa5b27b5f71a7dd
  ratified_on: 2026-09-21
  ratified_by: OWNER
  method: independent byte verification by the owner (Get-FileHash + git rev-parse)
  approved_entries: [A2-07]
  a2_07_normative_span_sha256: e96a0294b5eab21a13d6a4b6586299d91e444ca684facee93938555867dc6b03
base_ssot:
  document_id: WOLF15-5SCR-SSOT-V3.1-CANDIDATE
  path: docs/remediation/2026-09-09/source-binding/selected-ssot-v3.1.md
  sha256: 6daea387745ffa305d3cd55b0fee4f0efed79be21e24503c2a1f8a16c6a83902
  document_bytes_modified: false
scope: STRUCTURAL_TARGET_ONLY
effective_authority_model: BASE_SSOT_PLUS_EXPLICIT_AMENDMENTS
dual_authority: false
runtime_activation: EXPLICIT_ONLY
final_approver: OWNER
```

## 1. Why A2 is separate from A1

A1 already carries pending conflict overrides (A1-01 … A1-08), approved PressureRange entries
(A1-09 … A1-12) and its own ratification chain. Structural Target authority is a different object with a
different evidence class, so it gets its own artifact rather than being mixed in.

```text
EFFECTIVE STRATEGY AUTHORITY (target scope)
= SSOT v3.1 (6daea387…) + this amendment
```

A2 amends only the clauses its entries name. It grants **no** runtime activation and does not modify the base
SSOT bytes. Entry types are the same as A1: `CONFLICT_OVERRIDE` (contradicts and replaces a clause) and
`GAP_FILL` (v3.1 is silent).

Source: the 12B audit (`GAP12B_STRUCTURAL_TARGET_AUDIT.md`), open items T1–T10.

## 2. Entries

### A2-01 · CONFLICT_OVERRIDE · Target-first precedence

- **Source:** 12B audit (T1).
- **Base clauses:** §5, §17.1, §28, §16.1.
- **Base behavior — an internal contradiction.** §5 and §28 both list, verbatim,
  `PressureRange + route-specific ExecutionBox` **before** `nearest fresh structural target`. §17.1, in a
  section titled "S5 — Target-first trade geometry" under the heading "Correct solve order", lists the target
  at step 3 and the route-specific structural entry interval at step 4. §16.1 defines
  `ExecutionBox = route-specific legal entry geometry`, so §17.1 step 4 **is** the box. Both orders cannot hold.
- **Amended behavior:**
  - **§17.1 controls.** The detailed solve order is normative wherever the §5 / §28 summary ordering conflicts
    with it.
  - **Structural target selection precedes route-specific ExecutionBox materialization.**
  - §5 and §28 are summary text. They are amended/clarified wherever their displayed ordering implies that the
    ExecutionBox is materialized before the canonical target is known.
  - **`RouteEvaluation` is not moved.** §17.1 step 2 (active ContextEpoch and route) still precedes the target.
    What is forbidden is forming the *route-specific legal entry geometry* before the canonical target is known.
  - Canonical order:

    ```text
    DirectionalThesis + OrderedProof + PressureRange + ContextEpoch/RouteEvaluation
    → eligible structural target set
    → nearest fresh unconsumed structural target
    → route-specific ExecutionBox
    → structural invalidation
    → target-room / RR geometry
    ```

- **Reason:** §17.4 makes `target_room_interval` a member of the feasible-entry intersection. Selecting the
  target after the entry geometry exists would be circular. Resolving this in code by precedence would hide an
  authority decision inside an implementation.
- **shadow_required:** true · **replay_required:** true · **oos_required:** false · **runtime_activation:** EXPLICIT_ONLY.

### A2-02 · GAP_FILL · Nearest origin and directional distance

- **Source:** 12B audit (T2).
- **Base clauses:** §17.2, §17.4, §11.1, §11.2.
- **Base behavior:** §17.2 requires the "target struktural **terdekat**" that is also "belum dilewati pada
  decision time", but never states what `terdekat` is measured **from**.
- **Amended behavior:**
  - **Origin is the canonical decision price.**

    ```text
    decision_price = the latest authoritative, non-future price observation
                     valid at the canonical decision_time
    ```

    It comes from strategy-side closed-price authority (§11.2 `structural_candle_authority` /
    `analysis_observation_authority`), never from execution-price authority.
  - **Forbidden as origin:** a live broker ask/bid, future candle data, an eventual fill price, a route-derived
    entry price, or a reference price chosen because it makes RR work.
  - **Directional distance** (point targets):

    ```text
    BUY  : eligible iff target_price > decision_price ; distance = target_price - decision_price
    SELL : eligible iff target_price < decision_price ; distance = decision_price - target_price
    ```

  - **"Not passed at decision time" is a PRE-FILTER, not a tie-breaker.** For point targets it is the same
    comparison as the directional test: a BUY target at or below `decision_price`, or a SELL target at or above
    it, is ineligible and never enters the candidate set.
  - Selection takes the **minimum positive directional distance** after every eligibility predicate of A2-05
    has passed.
- **Zone targets:** the current representation is point-only (see the annex). If a zone representation is ever
  introduced, its canonical comparison boundary must be declared by the amendment that introduces it and must
  **not** be chosen inside an adapter.
- **Reason:** measuring from the entry interval is circular with §17.4, so the origin has to be fixed by
  authority rather than by convenience.
- **shadow_required:** true · **replay_required:** true · **oos_required:** false · **runtime_activation:** EXPLICIT_ONLY.

### A2-03 · GAP_FILL · Canonical freshness

- **Source:** 12B audit (T4).
- **Base clauses:** §17.2, §11.6.
- **Base behavior:** §17.2 requires `fresh` and never defines it. Audit/Replay v3 §18.3 stores a
  `freshness status` **and** a `tested count` but gives no transitions. §11.6 states that "Wall-clock age
  sendiri DILARANG menjadi authority".
- **Amended behavior:**
  - **Freshness is a structural / source-policy state, not a clock.** A wall-clock TTL is **not** canonical
    freshness authority.
  - The existing `valid_until` field is reclassified **`NON_CANONICAL / ADVISORY_ONLY`**. It may remain for
    telemetry, caching or advisory expiry, and it may **not** decide canonical structural-target eligibility.
  - The selector's canonical predicate becomes `freshness_status == FRESH`, not `now <= valid_until`.
  - **`tested_count` is evidence.** No universal threshold such as `tested_count <= N` is implied, and none may
    be introduced without its own amendment.
  - Freshness is produced by a **per-source-class policy**. `SWING`, `D1_SR`, `H4_SR`, `H1_SR`, `RANGE`,
    `BREAKOUT`, `LIQUIDITY` and `FIBONACCI` may form freshness differently, provided each policy is
    **explicit, deterministic, versioned, non-future and authority-approved**.
  - The target record must carry that provenance so a replay can prove which policy produced
    `freshness_status`. The **literal field names are not mandated** (owner ratification 2026-09-21): an
    equivalent provenance already present in a contract is acceptable, but the semantics —
    `freshness_status`, `tested_count` and the identity/version of the policy that produced them — must not
    be lost. **No such provenance exists in the current contract** (annex, item 2).
  - **Freshness is not consumption.** A target may legitimately be tested and still `FRESH`, tested and no
    longer fresh, or unconsumed yet not fresh. That is why §18.3 stores the two separately.
- **Reason:** a TTL cannot express "tested twice and still fresh", and §11.6 forbids age from being the
  authority. A universal tested-count threshold would reintroduce exactly the magic number A1-11 removed.
- **shadow_required:** true · **replay_required:** true · **oos_required:** false · **runtime_activation:** EXPLICIT_ONLY.

### A2-04 · GAP_FILL · Target consumption

- **Source:** 12B audit (T5).
- **Base clauses:** §17.2, §21.6, §13.
- **Base behavior:** §17.2 requires `unconsumed`; §18.3 stores `consumed_at` and `invalidated_at`; §21.6 has a
  `TARGET_CONSUMED` reason code. Nothing states what consumes a target.
- **Amended behavior:**
  - **Consumption is market-evidence truth:**

    ```text
    StructuralTarget consumption
    = the authoritative price path has satisfied the target's canonical completion condition
    ```

  - **Consumption is NOT** ExecutionBox creation, TradePlanCandidate creation, risk approval, order submission,
    a broker fill or a position. Those are trade-lifecycle truth and never consume a structural target.
  - **`ExecutionBox.CONSUMED` must not be imported.** It is a different object at a different layer and its own
    trigger is itself undefined (gap #12, owner decision 5 of the 12C audit).
  - **TEST ≠ CONSUME:**

    ```text
    TEST    = price interacts with the target without satisfying its completion condition
              → tested_count changes
              → freshness may change per the source policy of A2-03
              → NOT consumption
    CONSUME = the authoritative price path satisfies the completion condition
              → consumed_at is set
    ```

  - **Point targets (owner ratification 2026-09-21):**

    ```text
    consumed_at = the first authoritative target-completion evidence
    ```

    The **completion rule is source-policy-bound**, under the same discipline as A2-03: explicit,
    deterministic, versioned, non-future and authority-approved.
  - **This amendment deliberately fixes NO candle field as the completion criterion.** Whether completion
    is a wick touch, a close through the level, a bid touch or an ask touch is
    **`NOT_DEFINED_BY_AUTHORITY`** and must **not** be chosen inside an adapter or an implementation.
    Until a source policy declares it, a target has no completion rule and therefore cannot be consumed.
  - Evidence must be canonical: a tick that happens to be visible on a single feed is never sufficient.
  - **Zone targets — `ZONE_TARGET_RUNTIME_SEMANTICS = NOT_ACTIVE`** (owner ratification 2026-09-21).
    The canonical contract has no zone representation, so zone semantics are a forward-compatibility
    constraint and are **not active**. If a zone representation is ever introduced, its source must declare
    a `completion_boundary` (or an equivalent); entering the zone is a `TEST`, reaching the declared
    completion boundary is `CONSUMED`. A near edge, a far edge or a midpoint must **never** be chosen
    silently in an adapter.
  - **§13 liquidity FSM scope:** the §13 state machine is authority for the **`LIQUIDITY` source only**.
    Generalising it to `SWING`, `D1_SR`, `H4_SR`, `H1_SR`, `RANGE`, `BREAKOUT` or `FIBONACCI` is
    **`NOT_DEFINED_BY_AUTHORITY`** and is not granted here.
- **Reason:** without this separation a touch would silently consume a target, and trade-lifecycle events would
  leak into market-evidence truth.
- **shadow_required:** true · **replay_required:** true · **oos_required:** false · **runtime_activation:** EXPLICIT_ONLY.

### A2-05 · GAP_FILL · Canonical eligibility predicates

- **Source:** 12B audit.
- **Base clauses:** §17.2, §17.3.
- **Base behavior:** §17.2 states the predicate in prose. Read literally it is **six** conditions, not the four
  commonly quoted: the quoted `nearest / fresh / unconsumed / structural` omits `authoritative`,
  "berada di arah thesis" and "belum dilewati pada decision time".
- **Amended behavior — the canonical eligibility surface:**

  ```text
  1. STRUCTURAL                    (one of the §17.2 candidate sources; §17.3 target_source_required=STRUCTURAL)
  2. AUTHORITATIVE
  3. IN THESIS DIRECTION
  4. FRESH                         (A2-03)
  5. UNCONSUMED                    (A2-04)
  6. NOT PASSED AT decision_time   (A2-02)
  ```

  ```text
  all target candidates
  → structural? → authoritative? → in thesis direction? → fresh? → unconsumed? → not passed?
  → eligible set
  → nearest positive directional distance from decision_price
  → canonical selected target
  ```

  - `nearest` is applied **after** all six filters, never as one of them.
  - §17.2's prohibition stands: a farther target is forbidden while a nearer one is still active
    (§17.3 `nearest_target_cannot_be_skipped: true`).
  - Target selection never reads RR (Audit/Replay v3 §18.2: "Target dipilih sebelum RR; RR hanya menerima/
    menolak trade"). If the selected target later fails an RR threshold the setup is **rejected**; the next
    target is **not** selected instead.
- **shadow_required:** true · **replay_required:** true · **oos_required:** false · **runtime_activation:** EXPLICIT_ONLY.

### A2-06 · GAP_FILL · Deterministic tie policy

- **Source:** 12B audit (T9), derived from the existing selector rather than invented.
- **Base clauses:** §17.2, §17.3.
- **Base behavior:** authority requires "the nearest", but says nothing about two eligible targets at the same
  distance. The existing selector already orders by
  `(abs(Fraction(price) − Fraction(anchor_price)), target_id)` — exact decimal arithmetic via `Fraction`, so
  the comparison carries no floating-point error. Under A2-02 the anchor is `decision_price` and the
  directional pre-filter makes that absolute distance identical to the positive directional distance.
- **Amended behavior — frozen:**

  ```text
  primary key   = minimum positive directional distance from decision_price
  secondary key = ascending target_id
  ```

  This is exactly the existing deterministic order, restated so that determinism comes from authority rather
  than from an implementation detail. The implementation should express the directional distance explicitly
  rather than relying on `abs()` over a pre-filtered set, so the rule is readable without the filter.
- **`formed_at` is EXCLUDED** (owner decision 2026-09-21, final). Using it as a secondary key would silently
  create a market preference — *older structure preferred* or *newer structure preferred* — and no authority
  states that either is correct. That changes market behaviour, not merely determinism, and the existing
  two-key order is already a total order.
- **Nothing else may order candidates.** A selector may not silently prefer `D1` over `H4`, `SWING` over
  `FIBONACCI`, newer over older or older over newer. The following are all excluded unless a later
  amendment authorises them explicitly:

  ```text
  TargetSource precedence
  formed_at precedence
  RR precedence
  timeframe precedence
  source-quality score
  ```

- **`target_id` carries no structural claim.** It resolves determinism among materially equal-distance
  candidates and never asserts that one target is structurally better. It must therefore be **stable,
  deterministic, and independent of deployment, request or worker randomness**. If `target_id` is later
  found to be non-deterministic, that is a separate **identity gap** — it must not be patched by
  reintroducing `formed_at`.
- **shadow_required:** true · **replay_required:** true · **oos_required:** false · **runtime_activation:** EXPLICIT_ONLY.

### A2-07 · GAP_FILL · Structural target revision facts

- **Status:** `APPROVED` — ratified by the owner 2026-09-21 on exact bytes (`ratification_a2_07`).
- **Source:** 12B re-audit, criterion #14; owner decision 2026-09-21 to encode the facts as durable authority
  rather than rely on the 12B GO directive.
- **Base clauses:** §15.1, §21.6, §17.2.
- **Base behavior:** §15.1 lists `target-map revision` as a material re-evaluation trigger and §21.6 supplies
  target reason codes (`TARGET_MISSING`, `TARGET_CONSUMED`, `TARGET_ALREADY_PASSED`, …), but no clause says
  **what kind** of target revision occurred. Downstream geometry therefore has no authority-defined signal for
  when the target side has changed.
- **Amended behavior — the revision-fact vocabulary (closed, exactly four values):**

  ```text
  TARGET_UNCHANGED
  TARGET_MATERIAL_CHANGE
  TARGET_INVALIDATED
  TARGET_NO_LONGER_ELIGIBLE
  ```

  A revision fact compares the **previous** canonical selected target with the **current** canonical target
  selection.

  - **`TARGET_UNCHANGED`** — the previous and current canonical selections resolve to the same stable
    `target_id`, the canonical target material relevant to downstream geometry is unchanged, and the target
    still satisfies all six A2-05 predicates. No target-side structural re-evaluation follows.
  - **`TARGET_MATERIAL_CHANGE`** — the canonical selected-target result changed materially and target
    invalidation or ineligibility is not the cause. It covers both:

    ```text
    A. same target_id, but canonical material relevant to geometry changed
       (e.g. a canonical target price or material evidence revision)
    B. a different target_id is selected because the canonical eligible set or nearest solution changed
       (e.g. a new nearer eligible target became authoritative)
    ```

    Meaning: target-side structural re-evaluation is required. It does **not** by itself revise any
    ExecutionBox.
  - **`TARGET_INVALIDATED`** — the target source's authoritative structural policy explicitly invalidates the
    previously selected target. This is target-side structural invalidation only.
  - **`TARGET_NO_LONGER_ELIGIBLE`** — the previously selected target remains a known record with its evidence
    intact, but now fails one or more of the six A2-05 predicates, for example:

    ```text
    FRESH                → not fresh
    UNCONSUMED           → consumed
    NOT PASSED           → passed
    IN THESIS DIRECTION  → no longer in thesis direction
    AUTHORITATIVE        → authority lost
    ```

    The target is not deleted historically; it is only no longer eligible for canonical selection at that
    decision state.

- **Staleness, consumption, being passed, a direction change or loss of authority is NOT
  `TARGET_INVALIDATED`.** Each of those is `TARGET_NO_LONGER_ELIGIBLE` unless the source's structural policy
  also explicitly invalidates the target.
- **Precedence — frozen.** One classification reports exactly one value, the highest-semantic cause; the four
  values are not independent flags:

  ```text
  TARGET_INVALIDATED  >  TARGET_NO_LONGER_ELIGIBLE  >  TARGET_MATERIAL_CHANGE  >  TARGET_UNCHANGED
  ```

  ```text
  target explicitly invalidated by source authority          → TARGET_INVALIDATED
    (not TARGET_NO_LONGER_ELIGIBLE, although it is also no longer eligible)
  target consumed                                            → TARGET_NO_LONGER_ELIGIBLE
    (not TARGET_INVALIDATED)
  previous target still valid, fresh and unconsumed, but a
  nearer eligible target became authoritative                → TARGET_MATERIAL_CHANGE
  ```

- **Relation to §21.6.** The §21.6 reason codes stay the reason vocabulary. A2-07 adds a revision-fact
  vocabulary; it does not rename, replace or remove any reason code.
- **Target-side facts only — no ExecutionBox reaction.** A2-07 reports target-side canonical revision facts
  and nothing else. It must **not** encode any mapping from a target fact to an ExecutionBox FSM state or
  revision effect. All of the following are forbidden here:

  ```text
  TARGET_MATERIAL_CHANGE     → box_version++
  TARGET_INVALIDATED         → ExecutionBox.INVALIDATED
  TARGET_NO_LONGER_ELIGIBLE  → SUPERSEDED
  ```

  Every `A2 target fact → ExecutionBox FSM/revision effect` mapping, including how §16.3's
  "target/invalidation revision" trigger is interpreted, is **12C authority** and is left `NOT_DEFINED` by A2.
- **Not decided here.** A2-07 fixes no `target_id` derivation formula and no list of material target fields.
  Both belong to the implementation design, bound by A2-06 (`target_id` stable, deterministic, no randomness)
  and by this entry's semantics.
- **shadow_required:** true · **replay_required:** true · **oos_required:** false · **runtime_activation:** EXPLICIT_ONLY.

## 3. Non-normative annex

1. **Point vs zone — settled by inspection, not by choice.** `StructuralTargetV31.price` is a single
   `Price = Decimal(max_digits=28, decimal_places=12, gt=0)`. There is **no** zone, band, upper/lower or
   boundary field anywhere in the contract. The current canonical representation is therefore **point-only**,
   and the zone clauses in A2-02 and A2-04 are forward-looking requirements, not descriptions of today.
2. **Freshness-policy provenance is missing.** `StructuralTargetV31` carries `evidence_hash` but no
   `freshness_policy_id`/version, no `freshness_status`, no `tested_count`, no `invalidated_at`, and
   `TargetUniverseV31.policy_hash` binds the **execution** policy (`FX_MIN_TARGET_10P_V1`), not a freshness
   policy. A2-03 cannot be satisfied without adding that provenance. Recorded, not implemented.
3. **Audit/Replay v3 §18.3 fields still absent** from the current contract: `freshness status`, `tested count`,
   `invalidated_at`, `target_map_version`, `source timeframe/bar IDs`.
4. **T10 deferred, not dropped.** The relationship between a gross strategy RR and §17.3's frozen
   `minimum_net_rr: 1.5` is `NOT_DEFINED_BY_AUTHORITY`. It does **not** block target selection or target
   eligibility — it blocks final geometry / broker-feasibility acceptance. Target selection stays RR-blind,
   which is what preserves the anti-shopping invariant.
5. **Runtime-wired legacy floats.** `analysis/market_context_validator.py`, `analysis/signal_execution_gates.py`
   and the `microboost_*` family expose bare `key_support` / `major_resistance` / `tp1_support` floats and are
   wired through `pipeline/wolf_constitutional_pipeline.py`. They are `NONCONFORMANT` as structural-target
   authority. A2 neither deletes nor rewires them; any future adapter must ensure they cannot acquire canonical
   StructuralTarget authority merely because they are already wired.
6. **Adapter boundary (design intent, not authority).** An adapter may normalise identity, evidence lineage,
   freshness representation and completion/consumption representation. It may **not** invent structural
   authority, promote a bare float to a structural target without evidence, change the meaning of a target
   source, hide missing source coverage, or shop targets for RR.

## 4. Approval

**Ratified 2026-09-21.** The owner approved A2-01 … A2-06 per entry on content, then independently verified
the exact bytes of the draft (`sha256 4780c898…7608815`, git blob `d8433a12…a4ed1c9`). This document is the
approved successor of those exact bytes; the `ratification` block above pins the predecessor so the chain
stays provable without mutating the ratified draft in place.

**Why A2-01 needed no shadow/replay/OOS evidence to ratify** (owner reasoning, recorded): unlike A1-01, which
changes runtime block semantics, A2-01 changes no runtime behaviour. It resolves a proven internal
contradiction between two normative orderings by explicit governance precedence. The evidence flags on each
entry remain the evidence required before any *implementation* is activated, not before the clarification is
ratified.

**Approval grants no runtime activation and no implementation authority.**

```text
A2-01 APPROVED  ≠  StructuralTarget implementation authorized
A2-01 APPROVED  ≠  ExecutionBox implementation authorized
```

`grants_runtime_activation` stays `false` and every entry keeps `runtime_activation: EXPLICIT_ONLY`. The 12B
implementation gate stays closed until the owner opens it separately.

**A2-07 ratified 2026-09-21.** A2-07 was drafted on top of the approved document
(`sha256 9ca93cca…6fe165e7`); the `draft_revision` block pins that base and the sha256 of the A2-01 … A2-06
entries span (from `### A2-01` up to the start of `### A2-07`), so the earlier ratified text is provably
untouched. The owner then approved A2-07 on content and independently verified the exact draft bytes
(`sha256 01e9c76d…2253ba6`, git blob `39d380d3…a7dd`). This document is the approved successor of those bytes:
`ratification_a2_07` pins them, and `a2_07_normative_span_sha256` pins the A2-07 section with only its
status line excluded, so the ratified A2-07 semantics cannot change without detection.

```text
A2-07 APPROVED  ≠  StructuralTarget implementation authorized
A2-07 APPROVED  ≠  any ExecutionBox reaction defined (12C)
```
