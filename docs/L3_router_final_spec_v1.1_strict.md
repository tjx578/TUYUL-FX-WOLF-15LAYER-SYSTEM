# L3 Router Evaluator — Final Spec v1.1 (Strict)

> **Spec version**: 1.1  
> **Baseline**: v1.0 (frozen)  
> **Updated**: 2026-04-02  
> **Scope**: L3 trend confirmation constitutional governor  
> **Authority**: Analysis zone — no execution authority  

---

## Changelog from v1.0

| ID | Type | Description | Justification |
| ---- | ------ | ------------- | --------------- |
| C1 | **Threshold recalibration** | `HIGH ≥ 0.55`, `MID ≥ 0.25` (was `0.85` / `0.65`) | Sigmoid edge model (`bias=-3.5`) produces realistic output in 0.2–0.7 range. Old thresholds were unreachable in practice. |
| C2 | **NEUTRAL trend handling** | `NEUTRAL` trend with valid analysis → `WARN` (not `FAIL`) | NEUTRAL is a valid market state; failing it would block all non-directional confirmations. Pipeline should degrade gracefully, not halt. |
| C3 | **LOW_CONFIRMATION_SCORE blocker** | New `BlockerCode.LOW_CONFIRMATION_SCORE` added | Provides diagnostic visibility when confirmation score falls below `MID` threshold independently of other blockers. |
| C4 | **FLAT data → DEGRADED** | `data_quality=FLAT` maps to `FreshnessState.DEGRADED` (not `NO_PRODUCER`) | FLAT means data pipeline is alive but producing unusable values. `NO_PRODUCER` is reserved for truly absent data pipelines. |

---

## §1 Critical Blockers (frozen v1 + C3 extension)

| # | BlockerCode | Trigger |
| --- | ------------- | --------- |
| 1 | `UPSTREAM_L2_NOT_CONTINUABLE` | L2 `continuation_allowed == false` |
| 2 | `REQUIRED_TREND_SOURCE_MISSING` | Required trend source not in available set |
| 3 | `TREND_CONFIRMATION_UNAVAILABLE` | Trend not confirmed or NEUTRAL + very low score |
| 4 | `TREND_STRUCTURE_CONFLICT` | Directional trend contradicts WEAK structure with confidence ≤ 1 |
| 5 | `TREND_SOURCE_INVALID` | Trend source data invalid |
| 6 | `FRESHNESS_GOVERNANCE_HARD_FAIL` | Freshness == NO_PRODUCER or explicit hard fail |
| 7 | `WARMUP_INSUFFICIENT` | WarmupState == INSUFFICIENT |
| 8 | `FALLBACK_DECLARED_BUT_NOT_ALLOWED` | FallbackClass == ILLEGAL_FALLBACK |
| 9 | `CONTRACT_PAYLOAD_MALFORMED` | Required payload keys missing |
| 10 | `LOW_CONFIRMATION_SCORE` | **[v1.1]** Confirmation score < MID threshold (0.25) — diagnostic blocker |

---

## §2 Threshold Bands (recalibrated v1.1)

| Band | Threshold | Note |
| ------ | ----------- | ------ |
| `HIGH` | `≥ 0.55` | Calibrated for sigmoid edge model (`P_edge = sigmoid(W·X − 3.5)`) |
| `MID` | `≥ 0.25` | Realistic lower-bound for valid setups in sigmoid output distribution |
| `LOW` | `< 0.25` | Below viable confirmation — triggers FAIL |

**Rationale**: The v1.0 thresholds (0.85 / 0.65) assumed a linear 0–1 scoring model. The actual L3 engine uses a sigmoid edge model whose real-world output concentrates in 0.2–0.7. The recalibrated thresholds preserve the same relative selectivity within the actual output range.

---

## §3 Freshness States

| State | Meaning |
| ------- | --------- |
| `FRESH` | Candle age < 1h |
| `STALE_PRESERVED` | Candle age 1h–2h |
| `DEGRADED` | Candle age > 2h **OR** `data_quality=FLAT` **[v1.1]** |
| `NO_PRODUCER` | Data pipeline truly absent |

---

## §4 Warmup States

| State | Trigger |
| ------- | --------- |
| `READY` | H1 bars ≥ 30 |
| `PARTIAL` | H1 bars 20–29 |
| `INSUFFICIENT` | H1 bars < 20 |

---

## §5 Fallback Legality Matrix (frozen v1)

| FallbackClass | Legal | Effect |
| --------------- | ------- | -------- |
| `NO_FALLBACK` | ✅ | Clean path |
| `LEGAL_PRIMARY_SUBSTITUTE` | ✅ | PASS with warning |
| `LEGAL_EMERGENCY_PRESERVE` | ✅ | WARN only |
| `ILLEGAL_FALLBACK` | ❌ | FAIL — blocker triggered |

---

## §6 Compression Truth Table (v1.1)

| Condition | Status | continuation_allowed |
| ----------- | -------- | --------------------- |
| Any critical blocker | `FAIL` | `false` |
| Band == LOW | `FAIL` | `false` |
| Not confirmed | `FAIL` | `false` |
| Structure conflict | `FAIL` | `false` |
| **NEUTRAL trend + valid analysis** | **`WARN`** | **`true`** **[v1.1]** |
| Fresh + Ready + Directional + No conflict + HIGH/MID + No/Primary fallback | `PASS` | `true` |
| Legal degraded envelope (Stale/Degraded freshness, Partial warmup, Emergency fallback) | `WARN` | `true` |
| All other states | `FAIL` | `false` |

**NEUTRAL handling [v1.1]**: A NEUTRAL trend represents a confirmed non-directional market state. When analysis is otherwise legal (freshness ∈ {FRESH, STALE_PRESERVED, DEGRADED}, warmup ∈ {READY, PARTIAL}, band ∈ {HIGH, MID}), the result is `WARN` with `continuation_allowed=true`. This allows downstream layers to make their own assessment.

---

## §7 Evaluation Order (frozen v1)

1. Check upstream L2 legality
2. Check critical blockers
3. Evaluate freshness
4. Evaluate warmup
5. Evaluate fallback legality
6. Compute confirmation score
7. Check structure conflict
8. Compress status
9. Emit result

---

## §8 Authority Boundary (frozen)

- L3 is a trend confirmation legality governor only
- L3 must never emit: `direction`, `entry`, `execute`, `trade_valid`, `verdict`
- `status == FAIL` implies `continuation_allowed == false`
- `continuation_allowed == true` implies `next_legal_targets == ["L4"]`
