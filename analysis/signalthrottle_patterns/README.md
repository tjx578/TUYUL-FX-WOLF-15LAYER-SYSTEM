# Wolf15 SignalThrottle Golden Pattern Database

This folder stores analysis-layer pattern metadata for SignalThrottle pressure.
The registry never executes trades and never overrides Constitution/L12.

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
- `pair_role`
- `entry_permission`
- `management_action`
- `hold_policy`
- `chase_allowed`
- `block_reason`

The canonical Python registry is `registry.py`; YAML files mirror the same
operational contract for review and external tooling.
