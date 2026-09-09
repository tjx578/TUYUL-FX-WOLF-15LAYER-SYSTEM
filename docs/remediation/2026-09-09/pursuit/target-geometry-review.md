# K06 target-to-net caller checkpoint

Verdict: **PARTIAL_SOURCE_LOCAL_ONLY / INCOMPLETE / HOLD**. No canonical action
or milestone is closed. This follows the fixed-target kernel checkpoint, without
changing existing README files or the canonical register.

The new `solve_target_geometry_v31` caller consumes a TEST_ONLY target universe
and a geometry context without a preselected TP. It checks symbol, direction,
decision time, policy reference, declared source coverage and future evidence;
requires an explicit external verifier; selects the nearest fresh, unconsumed,
directional target; then invokes `solve_net_geometry_v31` exactly once.

Selection does not depend on which target would pass RR. A nearest target that
fails cost/entry constraints remains selected and returns no valid domain. An
off-grid nearest target is a validation error, not permission to try a farther
target. Only expired, consumed, already-passed or wrong-direction targets can be
excluded before selection. Equal-price ties use deterministic target identity.

The interface admits source labels for swing, D1/H4/H1 support/resistance, range,
breakout, liquidity and Fibonacci. **This is not proof that those sources have
been derived from real candles.** Derivation policy, anchor evidence, completeness
and freshness require the external attestor. Source coverage declared by the
input cannot authenticate itself. Missing attestor yields an explicit unbound
reason; false and truthy non-boolean verifier results are rejected. The test
receipt pins a whole-cohort digest, so removal of a nearer target invalidates it.

The new context contract shares existing net-geometry fields; it does not provide
a target default. Geometry validation remains on the fully constructed request.
The standalone kernel's existing caller interface remains available. No service
is switched to this new path, no policy is activated and no database is changed.
All result authority fields remain false.

Final validation: **77 tests passed, no failures/errors/skips** on Windows:
27 target-caller cases, 45 net-kernel regressions and 5 existing containment cases.
Exact JUnit identities match collection. This suite overlaps older suites and
must not be added to their totals. Ruff lint and format pass for all application
source (1,407 formatted files). Initial lint import/lambda issues were corrected
before the final run. Independent agent review is still unavailable following
the prior quota failure; review here is self-review.

Evidence: `evidence/target-geometry-validation.json`, `tg2-receipt.json`, `tg2.xml`
and `target-geometry-source.diff`. Each retained earlier receipt keeps its own
source binding; new source does not retrospectively upgrade old evidence.

Remaining K06 work is candle-derived structural evidence, a bound completeness
attestor and active policy, then strategy candidate/caller/persistence integration.
The interface does not close those dependencies. S03 PostgreSQL acceptance remains
45 existing + 7 producer + 11 consumer, unexecuted. No unchanged resource retry
was performed. New push remains held for the previously documented frontend
branch-trigger ambiguity; no main merge, Railway change or broker operation ran.
