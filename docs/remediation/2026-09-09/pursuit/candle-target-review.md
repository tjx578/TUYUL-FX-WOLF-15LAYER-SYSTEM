# Canonical candle derivation checkpoint

**PARTIAL_SOURCE_LOCAL_ONLY / INCOMPLETE / HOLD**, with no canonical action or
milestone closure. The previous turn made source and test progress; this turn
continues the K06 dependency without retrying unchanged external blockers.

The new provider uses the existing `CanonicalCandle` contract. It requires D1,
H4 and H1 frames, explicit expected windows, closed-as-of evidence, a supplied
policy hash, explicit target lifetime and a verifier over the entire snapshot.
The only implemented derivation policy is
`STRICT_THREE_CONTINUOUS_CANDLES_TEST_V1`, profile TEST_ONLY.

It derives strict three-candle swing highs/lows, confirms each at the right
candle close and scans subsequent H1 candles for touch/consumption. The latest
H1 close supplies the selection anchor. The derived universe then flows into
the existing nearest-target caller and net-RR kernel with its exact cohort hash.
No geometry-dependent fallback to a farther target is introduced.

| Acceptance exercised | Actual local result |
| --- | --- |
| BUY/SELL canonical fixtures reach target selection and feasible net geometry | PASS |
| Missing, gapped, future, unclosed, wrong-symbol or wrong-timeframe rows are rejected | PASS |
| A changed source price invalidates the pinned snapshot receipt | PASS |
| Missing attestor cannot produce a derived universe | PASS |
| H1 touch counts only after confirmation; equal neighboring extrema are not strict swings | PASS |
| D1/H4 confirmation splitting an H1 window is rejected | PASS |
| Reordering timeframe frames preserves cohort identity and result | PASS |
| Nonrepresentable float-derived prices are rejected without rounding | PASS |

Final suite: **90 passed, 0 failed, 0 errors, 0 skipped** on Windows, comprising
13 new candle-provider cases plus 77 overlapping caller/kernel/containment cases.
Do not sum this with earlier suites. Exact JUnit identities match collection.
Full repository Ruff lint and format pass (1,409 application files). Initial
fixture float-arithmetic failures are retained as `ct1`; fixtures were corrected
to explicit prices and the rejection became a negative test. Cross-timeframe
alignment was added during self-review before final `ct3` acceptance.

The SWING family is implemented across three timeframes. This does **not**
implement the complete SSOT target universe: D1/H4/H1 support/resistance, range,
breakout, liquidity and Fibonacci need their own bound derivation policies.
Continuous-window validation is not an approved trading calendar; gaps cannot
be excused without such a binding. The verifier in tests pins synthetic source
bytes and does not authenticate real broker or provider data. CanonicalCandle's
float representation remains a limitation; this provider does not silently
round an incompatible price. Worst-case consumption scans remain bounded by
input limits but have not been benchmarked.

No operational service, active policy, database or broker path is activated.
README and canonical register remain unchanged. PostgreSQL acceptance remains
45 existing + 7 producer + 11 consumer, unexecuted. New push remains held for the
previously recorded frontend source-branch trigger ambiguity. Independent agent
review remains unavailable following the earlier quota failure.

Evidence is in `evidence/candle-target-validation.json`, `ct3-receipt.json`,
`ct3.xml`, and `candle-target-source.diff`. Each historical receipt retains its
own source binding. Next work must reconcile the remaining target-family policy
and operational strategy candidate integration rather than treating this test
provider as completed S05 or natural DEMO readiness.
