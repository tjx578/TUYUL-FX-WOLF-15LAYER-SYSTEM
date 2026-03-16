# P0 Canonical Metrics

Status date: 2026-03-16
Scope: Cockpit metrics, synthesis metadata, and test coverage for canonical formulas.

## Canonical Metric Sources

- Wolf discipline (30-point): analysis.layers.L4_session_scoring
- TII canonical formula: analysis.l8_tii._compute_tii
- TII compatibility adapter: analysis.formulas.tii_formula.calculate_tii
- FRPC canonical formula: analysis.formulas.frpc_formula.calculate_frpc

## Cockpit Mapping Rules

Cockpit page reads score fields from /api/v1/verdict/all and supports both shapes below.

Shape A (preferred):

- scores.wolf_30_point.total
- scores.wolf_30_point.f_score
- scores.wolf_30_point.t_score
- scores.wolf_30_point.fta_score
- scores.wolf_30_point.exec_score
- scores.wolf_30_point.max_possible

Shape B (legacy fallback):

- scores.wolf_score
- scores.f_score
- scores.t_score
- scores.fta_score
- scores.exec_score

Additional status fields used in cockpit status bar:

- scores.tii
- scores.integrity
- gates.passed
- gates.total
- system.latency_ms

## Synthesis Formula Versioning

Formula version metadata is now attached at:

- synthesis.system.formula_versions

Current keys:

- tii: analysis.l8_tii._compute_tii:v1
- frpc: analysis.formulas.frpc_formula.calculate_frpc:v1
- wolf_30: analysis.layers.L4_session_scoring:wolf30-v1

## Verification Tests

Added tests:

- tests/test_tii_canonical.py
- tests/test_frpc_formula.py
- tests/test_execution_state_machine_registry.py

Intent:

- Guard canonical TII adapter behavior and input guards
- Ensure FRPC output bounds and clipping behavior
- Verify per-symbol execution registry isolation and backward-compat default path

## Notes

- Cockpit remains read-only UI and does not implement strategy or execution authority.
- Formula version strings are metadata for auditability and change tracking.
