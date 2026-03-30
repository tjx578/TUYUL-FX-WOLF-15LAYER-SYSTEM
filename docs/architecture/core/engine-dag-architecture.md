# TUYUL FX Engine DAG Architecture — Design Reference

**Version:** 1.1  
**Status:** Implemented (ADR-011)  
**Last Updated:** 2026-03-06

---

## 1. Overview

The TUYUL FX Wolf-15 pipeline (`pipeline/wolf_constitutional_pipeline.py`) runs
8 numbered phases plus two optional sub-phases. This document captures the
dependency graph, parallelization opportunities, and constitutional constraints.

Execution semantics are explicitly:

`SEMI-PARALLEL HALT-SAFE DAG`

`batch_1 -> sync barrier -> batch_2 -> sync barrier -> ...`

This runtime is intentionally not fully sequential and not fully parallel.
Trading runtime is treated as a capital-protection problem, so any batch
failure halts progression before the next batch.

### Design Philosophy

We chose a **hybrid approach** — standard Python `concurrent.futures.ThreadPoolExecutor`
inside the existing pipeline — over a standalone DAG framework (e.g. Apache Airflow,
Prefect, or a bespoke `core/dag_engine.py`).  The reasoning is in §7.

---

## 2. Current Pipeline Dependency Graph

                       ┌─────────────────────────────────────────────────────────┐
                       │         WOLF-15 CONSTITUTIONAL PIPELINE                 │
                       └─────────────────────────────────────────────────────────┘

  ╔══════════════════╗
  ║  INPUT           ║  symbol, tick_ts, system_metrics
  ╚══════════════════╝
          │
          ▼
  ┌───────────────────────────────────────────────────────────────────────────┐
  │ Phase 1 — FOUNDATION (SEQUENTIAL, halt-on-failure)                        │
  │                                                                           │
  │   L1 (Context/Bias) ──► L2 (MTA Structure) ──► L3 (Trend Confirmation)   │
  │                                                                           │
  │   If any layer raises, the pipeline returns early with verdict=NO_TRADE.  │
  └───────────────────────────────────────────────────────────────────────────┘
          │
          ▼
  ┌───────────────────────────────────────────────────────────────────────────┐
  │ Phase 2 — SCORING (SEQUENTIAL now, see §4 for future parallel option)     │
  │                                                                           │
  │   L4 (Wolf 30-Point Score) ──► L5 (Psychology/EAF)                       │
  └───────────────────────────────────────────────────────────────────────────┘
          │
          ▼
  ┌───────────────────────────────────────────────────────────────────────────┐
  │ Phase 2.5 — ENRICHMENT (PARALLEL 1-8, then SEQUENTIAL 9)  ← KEY CHANGE   │
  │                                                                           │
  │   ┌─────────────────────────────────────────────────────────────────┐     │
  │   │ ThreadPoolExecutor (max_workers=8)                               │     │
  │   │                                                                  │     │
  │   │  E1: Cognitive Coherence ─┐                                      │     │
  │   │  E2: Cognitive Context   ─┤                                      │     │
  │   │  E3: Risk Simulation     ─┤                                      │     │
  │   │  E4: Fusion Momentum     ─┼──► results dict ──► E9: Advisory     │     │
  │   │  E5: Fusion Precision    ─┤                    (sequential)      │     │
  │   │  E6: Fusion Structure    ─┤                                      │     │
  │   │  E7: Quantum Field       ─┤                                      │     │
  │   │  E8: Quantum Probability ─┘                                      │     │
  │   └─────────────────────────────────────────────────────────────────┘     │
  └───────────────────────────────────────────────────────────────────────────┘
          │
          ▼
  ┌───────────────────────────────────────────────────────────────────────────┐
  │ Phase 3 — SMC/STRUCTURAL (SEQUENTIAL now, see §4 for future)              │
  │                                                                           │
  │   L7 (SMC) ──► L8 (TII Integrity) ──► L9 (Entry Timing)                  │
  └───────────────────────────────────────────────────────────────────────────┘
          │
          ▼
  ┌───────────────────────────────────────────────────────────────────────────┐
  │ Phase 4 — RISK CHAIN (STRICT CHAIN, never parallel)                       │
  │                                                                           │
  │   L11 (R:R Calculator) ──► L6 (Correlation Risk) ──► L10 (Position Size) │
  │                                                                           │
  │   Each layer feeds precise numerical inputs to the next.                  │
  └───────────────────────────────────────────────────────────────────────────┘
          │
          ▼
  ┌───────────────────────────────────────────────────────────────────────────┐
  │ Phase 5 — VERDICT (SEQUENTIAL, constitutional authority)                  │
  │                                                                           │
  │   Synthesis ──► 9-Gate checks ──► L12 Verdict (SOLE DECISION AUTHORITY)  │
  └───────────────────────────────────────────────────────────────────────────┘
          │
          ▼
  ┌───────────────────────────────────────────────────────────────────────────┐
  │ Phase 6 — GOVERNANCE (SEQUENTIAL)                                         │
  │                                                                           │
  │   L13 two-pass reflection (pre-trade + post-trade governance)             │
  └───────────────────────────────────────────────────────────────────────────┘
          │
          ▼
  ┌───────────────────────────────────────────────────────────────────────────┐
  │ Phase 7 — SOVEREIGNTY (SEQUENTIAL)                                        │
  │                                                                           │
  │   L15 sovereignty enforcement (prop-firm compliance gatekeeper)           │
  └───────────────────────────────────────────────────────────────────────────┘
          │
          ▼
  ┌───────────────────────────────────────────────────────────────────────────┐
  │ Phase 8 — EXPORT (SEQUENTIAL)                                             │
  │                                                                           │
  │   L14 JSON export + final signal assembly                                 │
  └───────────────────────────────────────────────────────────────────────────┘
          │
          ▼
  ┌───────────────────────────────────────────────────────────────────────────┐
  │ Phase 8.5 — V11 SNIPER FILTER (SEQUENTIAL, post-pipeline)                 │
  │                                                                           │
  │   V11 edge validation (run only when L12 verdict = EXECUTE)               │
  └───────────────────────────────────────────────────────────────────────────┘
          │
          ▼
  ╔══════════════════╗
  ║  OUTPUT          ║  verdict, scores, enrichment, signal_id …
  ╚══════════════════╝

---

## 3. Parallelization Matrix

| Phase | Components | Current Mode | Can Parallelize? | Blocker |

| ------- | ----------- | -------------- | ----------------- | --------- |
| 1 | L1, L2, L3 | Sequential | ❌ No | L2 needs L1 output; L3 needs L2; halt-on-failure chain |
| 2 | L4, L5 | Sequential | ⚠️ Maybe | L5 (psychology) is enriched by L4 score in practice |
| 2.5 E1-8 | 8 enrichment engines | **Parallel** ✅ | ✅ Yes | **Implemented** — independent computations |
| 2.5 E9 | Advisory engine | Sequential | ❌ No | Must receive E1-8 outputs |
| 3 | L7, L8, L9 | Sequential | ⚠️ Maybe | L8 integrity feeds L9 entry timing |
| 4 | L11→L6→L10 | Sequential | ❌ No | Strict numerical data chain |
| 5 | Synthesis, Gates, L12 | Sequential | ❌ No | Constitutional — L12 is sole authority |
| 6 | L13 | Sequential | ❌ No | Two-pass model (depends on own prior pass) |
| 7 | L15 | Sequential | ❌ No | Single sovereignty check |
| 8 | L14 | Sequential | ❌ No | Consumes all prior outputs |
| 8.5 | V11 | Sequential | ❌ No | Post-pipeline filter |

---  <!-- ensure no standalone `|` line exists before/after this separator -->

## 4. Constitutional Constraints

The following 6 rules govern every DAG change and **may never be overridden**:

### Rule 1 — Halt-on-Failure (Phase 1)

L1 → L2 → L3 is a strict sequential chain.  Any unhandled exception in this
phase causes the pipeline to return `verdict = NO_TRADE` immediately.  No layer
in Phase 1 may be parallelized.

### Rule 2 — L11 → L6 → L10 Strict Chain

The risk chain (Phase 4) carries precise numerical state: R:R ratio from L11
feeds L6, and the correlation-adjusted risk feeds L10 position sizing.  These
layers **must never run in parallel** regardless of future architectural changes.

### Rule 3 — L12 Sole Authority

Layer 12 is the **only** component permitted to emit a `EXECUTE` / `HOLD` /
`NO_TRADE` verdict.  No enrichment engine, analysis layer, or runner may add
execution authority.  The parallel enrichment work in Phase 2.5 produces metrics
only — it never bypasses or influences L12 directly (only via the synthesis dict).

### Rule 4 — V11 Post-Pipeline Only

V11 (Sniper Filter / Edge Validator) runs **after** L12 has issued its verdict.
It may block a trade based on edge conditions, but it is not part of the core
verdict loop.  Moving V11 before L12 would violate this rule.

### Rule 5 — Journal Immutability

The journal (J1–J4) is append-only.  No parallel worker may overwrite or
replace journal entries.  Journal writes triggered during or after enrichment
must be sequentially serialised.

### Rule 6 — Enrichment Resilience (Non-Fatal Engines)

Individual enrichment engine failures must **never** block the pipeline or other
engines.  Each engine is wrapped in an isolated try/except.  In parallel mode,
a single Future failure is caught per-future; it logs a warning, appends to
`EnrichmentResult.errors`, and leaves the other futures unaffected.

---

## 5. Enrichment Engine Parallel Architecture

  EngineEnrichmentLayer.run()
        │
        ├── _build_candles()        (sync, I/O from context bus)
        ├── _build_cognitive_state() (sync, pure computation)
        │
        │   if_PARALLEL_ENRICHMENT:
        │       │
        │       └──_run_engines_parallel()
        │                │
        │                │   ThreadPoolExecutor(max_workers=8)
        │                │       │
        │                │       ├── Future:_run_engine_safe("cognitive_coherence", …)
        │                │       ├── Future:_run_engine_safe("cognitive_context",   …)
        │                │       ├── Future:_run_engine_safe("risk_simulation",     …)
        │                │       ├── Future:_run_engine_safe("fusion_momentum",     …)
        │                │       ├── Future:_run_engine_safe("fusion_precision",    …)
        │                │       ├── Future:_run_engine_safe("fusion_structure",    …)
        │                │       ├── Future:_run_engine_safe("quantum_field",       …)
        │                │       └── Future:_run_engine_safe("quantum_probability", …)
        │                │
        │                │   as_completed(timeout=11s)
        │                │       ├── success  → setattr(result, field_name, out)
        │                │       ├── failure  → result.errors.append(msg); log WARNING
        │                │       └── timeout  → result.errors.append(msg); log WARNING
        │
        │   else (_PARALLEL_ENRICHMENT is False):
        │       └──_run_engines_sequential()  (original behaviour, for debugging)
        │
        └── Engine 9: Advisory (always sequential, uses result from above)
                │
                └── _aggregate()  →  EnrichmentResult (unchanged contract)

### Error Isolation

_run_engine_safe(name, fn, *args, **kwargs)
    try:
        out = fn(*args,**kwargs)
        return (name, out, None)       # success
    except Exception as exc:
        return (name, None, str(exc))  # isolated failure

A failure in any one future never propagates to other futures.  The executor
`.as_completed()` loop catches both task-level exceptions (via the `error` tuple
element) and Future-level exceptions (via `future.result()` re-raise).

---

## 6. Performance Estimates

| Scenario | Timing |

| --------- | -------- |
| Sequential (old) — engines 1-8 | ~8 × 30ms = 240ms |
| Sequential (old) — engine 9 | ~30ms |
| **Sequential total** | **~270ms** |
| Parallel (new) — engines 1-8 | ~30ms (dominated by slowest engine) |
| Sequential (new) — engine 9 | ~30ms |
| **Parallel total** | **~60ms** |
| **Estimated speedup** | **~4.5×** |

Timings are estimates based on ~30ms per engine at typical market-hours load.
Actual speedup depends on thread scheduling overhead and GIL contention (minimal
here because engines are I/O-bound, not CPU-bound pure Python loops).

The `elapsed_ms` field in `EnrichmentResult` records wall-clock time for each
run; use `DEBUG`-level logging (`[Enrichment] parallel engines 1-8 elapsed=…`)
to measure actual parallel speedup in production.

---

## 7. Future Scaling

### Phase 2: L4 ∥ L5 (conditional)

L4 (Wolf 30-Point Score) and L5 (Psychology/EAF) are candidates for parallel
execution **if** L5 is confirmed to not read L4 output at call time.  Before
parallelizing, audit `analysis/l5_psychology.py` for any `layer_results["L4"]`
reads during its main scoring pass.  If it only reads L1/L2/L3, parallelization
is safe.

### Phase 3: L7 ∥ L8 ∥ L9 (conditional)

L7 (SMC Structure), L8 (TII Integrity), and L9 (Entry Timing) are candidates if
they are confirmed to read only Phase 1/2 outputs.  Audit inter-layer dependencies
before enabling.

### General Extension Pattern

To parallelize any new set of independent layers, follow the same pattern used
for enrichment engines:

python
with concurrent.futures.ThreadPoolExecutor(max_workers=N) as executor:
    futures = {executor.submit(fn, *args): label for label, fn, args in tasks}
    for future in concurrent.futures.as_completed(futures, timeout=TIMEOUT):
        label = futures[future]
        try:
            result = future.result(timeout=TIMEOUT)
        except Exception as exc:
            handle_error(label, exc)

Key requirements for any newly parallelized group:

1. Layers must be **read-only** with respect to shared mutable state.
2. Failures must be **non-fatal** (wrapped in try/except per future).
3. Constitutional authority (L12) must remain downstream and sequential.

---

## 8. Decision Record — Hybrid over Standalone DAG Framework

**Decision:** Use `concurrent.futures.ThreadPoolExecutor` inside the existing
pipeline rather than introducing a dedicated DAG library (Airflow, Prefect, or a
bespoke `core/dag_engine.py`).

**Rationale:**

| Criterion | Hybrid (chosen) | Standalone DAG |

| ----------- | ---------------- | ---------------- |
| Dependency footprint | None (stdlib only) | Large (Airflow: 50+ deps) |
| Operational complexity | Low (in-process) | High (separate scheduler) |
| Latency | Microseconds overhead | 10s–100s ms scheduler overhead |
| Fits current scale | ✅ Yes (1 pipeline instance) | ❌ Overkill |
| Testability | Standard pytest mocks | Requires DAG test harness |
| Constitutional isolation | Easy — same process, same guards | Harder to enforce across services |

The hybrid approach satisfies the performance target (~60ms Phase 2.5) with zero
new production dependencies and no change to the `EngineEnrichmentLayer` public
API (`__init__`, `run`, `EnrichmentResult`).
