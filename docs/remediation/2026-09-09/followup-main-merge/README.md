# Current-main integration after S01/S03 publication

The remote main branch advanced to `e3a0d8c83d5d8de60645a1d4f7c00f66fe9d5941` during publication. GitHub reported conflicts with remediation head `c715b3a8d7949b2e3ca3476cfc822cad4748461b`. This followup supersedes the earlier statement that current-main changes had not been integrated.

The reviewed merge retains the unconditional API-only ownership guard and readiness 503 behavior. It also retains incoming read-only startup validation, suppression of PG initialization/outbox/relay/peer-health/candle startup, and credential-free startup attestation. Embedded orchestrator creation remains absent; its attested startup state is false. The migration ownership test retains mocked subprocess behavior and the redactor assertion. The owner-startup test patches standard-library threading directly and retains all containment assertions.

**434 collected = 434 JUnit results, zero failures/errors/skips.** This includes the earlier 334 cases plus 100 current-main startup/ownership cases; these counts must not be added together. The same pinned Windows API environment was used, source hashes remained stable during the run, and all tested source bytes were checked against the staged tree. Four relevant source/test files passed Ruff lint and format. Independent review is in `merge-review.md`; exact identities and execution evidence are in `validation.json` and `evidence/`.

The incoming Codex settings are inherited as current-main content; no settings or permission commands were executed from those files. No Railway configuration was applied. The initial receipt-helper attempt failed decoding Windows UTF-8 before test execution; only the helper decoding was corrected, then the accepted 434-case run executed.

At prior published head c715b3a8, CI run34275592567 reported seven failed jobs with runner_id=0 and no execution steps. This does not prove source regression or a billing cause. No workflow rerun or billing action was taken. Final publication metadata is checked separately after the merge commit to avoid a commit/CI receipt loop.

Program status remains **INCOMPLETE / HOLD, 0/6 milestones complete**. S01 policy/schema/historical-copy gaps and S03 active binding/durable runtime acceptance remain as recorded in the S01/S03 register. This local merge validation does not establish full remote CI, Linux, database, browser, deployment or broker acceptance.
