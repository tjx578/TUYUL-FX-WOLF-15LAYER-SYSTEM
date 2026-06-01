# Wolf15 SignalThrottle Golden Pattern Database

This folder stores analysis-layer pattern metadata for SignalThrottle pressure.
The registry never executes trades and never overrides Constitution/L12.

Golden references are evidence sources, not pair locks. A pattern ID describes
a universal market condition; public SignalJSON emits these as
`reference_cases[]` while older internal objects may still expose
`golden_reference` / `golden_references` for compatibility. Pair names add
calibration such as pip size, basket/theme alignment, spread, session behavior,
and volatility.

Core rule:

```text
SignalThrottle = pressure radar.
Microboost = priority/lifecycle booster.
Allowed = provisional direction.
Final direction requires phase, theme, price context, risk, and tradeplan readiness.
```

Use `analysis.signalthrottle_patterns.match_golden_patterns()` to enrich live
features with:

- `selected_pattern_id`
- `matched_patterns`
- `pattern_tier`
- `pattern_family`
- `pattern_score`
- `pattern_match_score`
- `execution_readiness_score`
- `pattern_scope`
- `applies_to`
- `reference_cases`
- `pair_calibration`
- `pattern_context`
- `theme_context`
- `tradeplan_preview`
- `execution_gate`
- `lifecycle`
- `pattern_search_space`
- `pattern_db_candidates_scanned`
- `pattern_db_exact_matches`
- `pattern_db_fuzzy_matches`
- `pattern_bottlenecks`
- `pattern_match_diagnostics`
- `entry_permission`
- `management_action`
- `hold_policy`
- `chase_allowed`
- `block_reason`
- `jpy_alignment_status`
- `theme_alignment_status`
- `alignment_missing_reason`

Compatibility fields such as `golden_reference`, `golden_references`,
`pair_specific_calibration`, and `pair_role` may still exist inside internal
Python objects for older callers. Emitted SignalJSON payloads should treat
`reference_cases[]` and `pair_calibration{}` as the public identity contract:
reference cases are historical proof only, while the live symbol is calibrated
from current pair context.

`pattern_match_score` describes how strongly the historical/golden pattern is
recognized. `execution_readiness_score` describes whether the current market
context is ready for execution. `pattern_score` remains as a backward-compatible
readiness score and should not be used alone to downgrade a Tier-S pattern.

The matcher now runs a database-wide retrieval pass across every
`GOLDEN_PATTERNS` entry. Exact IDs from prior logs or nested
`pattern_context` win first; semantic/fuzzy matches are lower-weight support
signals. `pattern_bottlenecks` explains why a recognized watch pattern did not
become a final SignalJSON, for example missing theme snapshots, provisional RR
fallback targets, missing support/resistance ladders, or M15 confirmation gates.

Watch events must expose `watch_direction` while keeping
`validated_direction=None` until structure, M15 confirmation, and execution
readiness are all satisfied.

The canonical Python registry is `registry.py`; YAML files mirror the same
operational contract for review and external tooling.
