# Wolf15 SignalThrottle Golden Pattern Database

This folder stores analysis-layer pattern metadata for SignalThrottle pressure.
The registry never executes trades and never overrides Constitution/L12.

Golden references are evidence sources, not pair locks. A pattern ID describes
a universal market condition; `golden_reference` / `golden_references` only
record where that condition was historically validated. Pair names add
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
- `golden_reference`
- `pattern_scope`
- `applies_to`
- `golden_references`
- `pair_specific_calibration`
- `pair_role`
- `entry_permission`
- `management_action`
- `hold_policy`
- `chase_allowed`
- `block_reason`
- `jpy_alignment_status`
- `theme_alignment_status`
- `alignment_missing_reason`

`pattern_match_score` describes how strongly the historical/golden pattern is
recognized. `execution_readiness_score` describes whether the current market
context is ready for execution. `pattern_score` remains as a backward-compatible
readiness score and should not be used alone to downgrade a Tier-S pattern.

Watch events must expose `watch_direction` while keeping
`validated_direction=None` until structure, M15 confirmation, and execution
readiness are all satisfied.

The canonical Python registry is `registry.py`; YAML files mirror the same
operational contract for review and external tooling.
