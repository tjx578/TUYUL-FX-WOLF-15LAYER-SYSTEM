# Full-suite followup: obsolete dashboard contract, AST imports, governance entrypoints

The first complete candidate CI run `34342664740` exposed 15 setup errors in the retired Vercel `connectionState.ts` threshold tests, an analysis import-guard false positive from prose, and two release-gate package import failures. This followup changes four files:

- `tests/test_connection_state_thresholds.py`: replaces 15 obsolete constant/file assertions with 15 executable cases against the existing selected Railway `wolf15-v2/model.mjs`. Cases require valid observation state, timestamp, source policy id, numeric positive age limit; preserve source STALE/STALE_PRESERVED; and exercise the exact freshness expiry boundary. Missing Node/model is a failure, never a skip. No dashboard application code changed.
- `tests/unit/test_analysis_boundary.py`: validates AST import nodes instead of documentation substrings. Recursive analysis scan includes package initializers and missing source fails. Fixtures reject direct, aliased, multi-import, relative, conditional and deferred execution imports; prose/comments/unrelated names remain legal. Existing order-placement and dashboard-mutation boundaries remain checked.
- `scripts/ci/railway_release_source_gate.py`: selects package-relative or standalone sibling import of the governance helper according to Python package context. Governance enforcement is retained.
- `tests/test_railway_release_source_gate.py`: supplies bounded read-only CI/governance API fixtures to real validators, adds module/standalone success and actual unprotected-main rejection, and exercises both real governance CLI invocation forms. No live network/provider call is used by these tests.

Command:

```text
python -m pytest tests/test_connection_state_thresholds.py tests/unit/test_analysis_boundary.py tests/test_railway_release_source_gate.py tests/test_p1_governance_gate.py --import-mode=importlib -q -p no:cacheprovider --override-ini addopts='' --junitxml=docs/remediation/2026-09-09/p1-integration/governance/followup-tests.xml
```

Result: **192 passed, zero failed/errors/skipped, 14.09 seconds**. Ruff on affected tests and both release/governance helpers passed. Whitespace diff check passed. `followup-tests.xml` is the executed local receipt; remote full-suite rerun remains the parent's next gate.

## Bounded review of parent containment followups

Reviewed the actual parent diff for C2 rejection mapping, cold/warm price-quality fixtures, pressure log capture, websocket recording clients, and the P4 consumer allowlist. No authority-broadening defect found in those edits. The C2 change preserves rejection and only distinguishes unsupported currency. Both cold and warmed stale-price cases still assert `valid_for_execution is False`. Log capture fixes INFO visibility without changing emitters. Websocket timing thresholds remain unchanged and delivery count/order are asserted.

The two newly recognized existing V3.1 consumers import `classify_m15_completion` and `ClosedCandleAuthorityRefV1`, respectively. Their validated policy/evidence models retain `Literal["TEST_ONLY"]`; the reviewed files introduce no API or execution import. The exact file/module allowlist remains closed to other consumers. This static scoped review is not production activation proof, a full dependency-graph audit, or closure of runtime/provider gates.

No commit, push, provider setting change or production execution was performed by this subtask. Edits frozen for parent integration.
