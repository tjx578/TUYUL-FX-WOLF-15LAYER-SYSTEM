# Docs Hygiene local acceptance

Candidate checkout at check: `c7e9762993349fcf9e4f222133d8188d0d7425fa` plus the in-progress integration and the four documentation edits bound by SHA-256 in `receipt.json`. This is local working-tree evidence, not an immutable final candidate or remote CI receipt.

The patch fixes 19 broken relative links without rewriting historical content:

| File | Links corrected |
| --- | ---: |
| `docs/architecture/contracts/operational-api-event-acceptance-spec.md` | 2 |
| `docs/architecture/guardrails/tick-spike-filter.md` | 5 |
| `docs/architecture/operations/go-live-checklist.md` | 7 |
| `docs/architecture/operations/observability-async-workers.md` | 5 |

All destinations already exist in the repository. Link fragments are preserved. The correction adds the required parent-directory traversal from nested architecture documents to repository files; it does not invent or recreate removed content. The workflow checker validates filesystem existence only and does not validate heading/line anchors or the current truth of operational prose.

## Verification

`python docs/remediation/2026-09-09/p1-integration/docs/check_docs.py` extracts and executes the current workflow run blocks with Git Bash and Python 3.11. The gate's GitHub job-result expressions are replaced with actual preceding local outcomes. Workflow byte hash, edited file hashes, per-step exit codes and extracted-script hashes are in `receipt.json`.

- Architecture reading-order integrity: PASS, all 12 expected files exist.
- Legacy quarantine source scan and index existence: PASS.
- Architecture cross-references: PASS, 64 Markdown files checked, zero broken local-path links.
- Combined local Docs Gate: PASS.
- `git diff --check -- docs/architecture docs/remediation/2026-09-09/p1-integration/docs`: PASS.

`baseline-broken-links.json` records the 19 pre-edit failures from HEAD. `first-pass/` retains an intermediate failed check that caught two fragment-bearing links; these were then corrected and the complete check rerun successfully. The final results are at this directory's top level.

Remote Docs Hygiene workflow: NOT_EXECUTED by this subtask. Parent must bind the final committed candidate and its remote checks separately. No production/runtime acceptance, deployment, provider configuration, governance enforcement, or trading-readiness gate is closed by Markdown link checks. No workflow, application source, or historical acceptance claim was changed by this subtask.
