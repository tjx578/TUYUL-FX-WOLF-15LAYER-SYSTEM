# Wolf 30-Point — Divergence Map: Curriculum vs Production

> **Status**: Frozen baseline — update only via governance process.
> **Source**: Curriculum document "Dasar Kuantifikasi Peluang" vs repo code analysis.
> **Date**: 2026-04

## 1. Purpose

This document tracks known divergences between the pedagogical curriculum
(Wolf-15 Layer scoring doctrine) and the production repo implementation.
Both sources are valid, representing different design intents:

| Source | Intent |
| --- | --- |
| **Curriculum** | Ideal-state doctrine — strict gates, aspirational thresholds |
| **Production** | Pragmatic operational baseline — proven in live/prop context |

Divergences are tracked, not automatically resolved. Each divergence has
a governance path (RECONCILE / KEEP_BOTH / DEFER).

---

## 2. Scoring Component Alignment

| Component | Curriculum Max | Production Max | Status |
| --- | --- | --- | --- |
| F-score (Fundamental) | 8 | 8 | **ALIGNED** |
| T-score (Technical) | 12 | 12 | **ALIGNED** |
| FTA-score (Alignment) | 5 | 5 | **ALIGNED** |
| Exec-score (Execution) | 5 | 5 | **ALIGNED** |
| **Wolf Total** | **30** | **30** | **ALIGNED** |

---

## 3. Grade Thresholds

| Grade | Curriculum | Production | Delta | Governance |
| --- | --- | --- | --- | --- |
| PERFECT | ≥ 27 | ≥ 27 | 0 | ALIGNED |
| EXCELLENT | ≥ 24 | ≥ 23 | −1 | KEEP_BOTH — production more lenient by design |
| GOOD | ≥ 20 | ≥ 18 | −2 | KEEP_BOTH — pragmatic deployment threshold |
| MARGINAL | ≥ 15 | ≥ 13 | −2 | KEEP_BOTH — wider capture window |
| FAIL | < 15 | < 13 | −2 | KEEP_BOTH — production tolerates narrower fail band |

> **Policy**: Production thresholds are operationally validated. Curriculum
> thresholds represent aspirational targets. Profile system (Phase D) allows
> runtime switching between both via `curriculum_grade` field.

---

## 4. Sub-Threshold Divergences

| Sub-Threshold | Curriculum | Production (constitution.yaml) | Status |
| --- | --- | --- | --- |
| `technical_min` | 9 | 9 | **ALIGNED** |
| `fta_min` | 3 | 3 | **ALIGNED** |
| `execution_min` | 4 | 4 | **ALIGNED** |
| `fundamental_min` | 5 | **MISSING** | **GAP** — Phase B adds to config |

---

## 5. Constitutional Gate Divergences

| Gate | Curriculum | Production | Status |
| --- | --- | --- | --- |
| `fta_conflict_veto` | Hard veto on L1↔L2 conflict | **NOT IMPLEMENTED** | **GAP** — Phase B adds config, Phase C enforces |
| `scoring_floor` (wolf_30_point.min_score) | 22 | 22 | **ALIGNED** |
| 9-gate constitutional | 9 gates | 10 gates in production | **PRODUCTION SUPERSET** — acceptable |

---

## 6. Bayesian Enrichment

| Feature | Curriculum | Production | Status |
| --- | --- | --- | --- |
| Bayesian posterior | Described conceptually | Fully implemented (L4 v3) | **PRODUCTION AHEAD** |
| Prior regime conditioning | Described | Implemented | ALIGNED |
| Evidence integration | Described | Implemented with clamp/cap | ALIGNED |

---

## 7. FTA Conflict Detection

| Aspect | Curriculum | Production | Status |
| --- | --- | --- | --- |
| L1↔L2 direction comparison | Core requirement | Computed in `_compute_fta_score()` as `direction_match` | **DATA EXISTS** |
| Explicit conflict flag | Required for veto | **NOT EMITTED** as separate flag | **GAP** — Phase B adds `fta_conflict` to payload |
| Veto enforcement | Hard veto | **NOT ENFORCED** | **GAP** — Phase C adds to L4 constitutional |

---

## 8. Profile System

| Aspect | Curriculum | Production | Status |
| --- | --- | --- | --- |
| Runtime profile switching | Implied | `ConfigProfileEngine` exists with CRUD + merge | **PRODUCTION AHEAD** |
| Curriculum-strict profile | Required for full alignment | **NOT YET CREATED** | **GAP** — Phase D creates profile YAML |
| Env-var bootstrap | Required | **NOT YET WIRED** | **GAP** — Phase D adds `WOLF15_CONSTITUTION_PROFILE` |

---

## 9. Resolution Timeline

| Phase | Scope | Divergences Addressed |
| --- | --- | --- |
| **A** (this doc) | Baseline freeze | Document all divergences |
| **B** | Additive config + payload | `fundamental_min`, `fta_conflict_veto` config, `fta_conflict` flag, `curriculum_grade` |
| **C** | Light enforcement | L4 constitutional enforces `fundamental_min` + `fta_conflict_veto` |
| **D** | Profile integration | Profile YAMLs, env bootstrap, `ConfigProfileEngine` autoload |
| **E** | Telemetry + adapter | Verdict payload, effective constitution adapter |

---

## 10. Change Log

| Date | Change | Author |
| --- | --- | --- |
| 2026-04 | Initial divergence map created | System |
