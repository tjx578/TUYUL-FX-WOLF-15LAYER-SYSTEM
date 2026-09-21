# Strategy 5S-CR SSOT v3.1: Amendment A2 — Structural Target Authority Clarification (DRAFT)

```yaml
amendment_id: WOLF15-5SCR-SSOT-V3.1-A2
status: DRAFT_NOT_APPROVED
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

This record is a DRAFT. Approval needs the owner's explicit decision per entry together with the evidence each
entry declares. A2 grants no runtime activation, and approving A2 is not authorization to implement: the 12B
implementation gate stays closed until it is opened separately.
