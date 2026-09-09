# WOLF15 release audit: HOLD

Observation: 2026-09-08 19:20 UTC / 2026-09-09 03:20 WITA. This report covers P1 and P4 release evidence and GitHub/Railway inspection. It does not claim all 41 actions are complete.

## Source and GitHub

The current remote main is `773150952311db3dbf5188f36536b7837d8ec296`, verified independently through GitHub branches/main and `git ls-remote`. Historical `1837f4b7cbded620c35933af980e9abd166de39e` is its parent. The user's original checkout remained at `ec31631864204ca183079966d7834338f7a986cd`; it was not reset or edited by this audit. PR #422 already integrated the new owner login/dashboard source, so old owner-login candidates must not be blindly reapplied.

All six selected PRs remain OPEN. GitHub's returned baseRefOid is PR metadata, not the newly observed main head:

| PR | Current head | Draft | Mergeability | Reported checks |
|---|---|---|---|---|
| 413 | f5cd076b86e5bc3ed22242f75a896ef453871d90 | yes | MERGEABLE / UNSTABLE | 1 failure, 0 success |
| 414 | dd27ae87d0207466caad4c3e098224112ac0eaf7 | no | MERGEABLE / UNSTABLE | 27 failures, 0 success, 1 other |
| 415 | 128472045277632b3a091086c5fd1b7cbdf40549 | yes | MERGEABLE / UNSTABLE | 19 failures, 0 success |
| 416 | 2ee5239ec0e029805c54b364d973f33c5674e9e7 | yes | MERGEABLE / UNSTABLE | 15 failures, 0 success |
| 418 | a28ee83b838df259f89a87153f16d2c4cac3dc92 | yes | CONFLICTING / DIRTY | 27 failures, 0 success |
| 419 | 3f4b8293c6c70b010bbbb85306379ba54079e125 | yes | MERGEABLE / UNSTABLE | 23 failures, 0 success |

Current main [CI run 34268107881](https://github.com/tjx578/TUYUL-FX-WOLF-15LAYER-SYSTEM/actions/runs/34268107881) failed. All six jobs report `runner_id=0` and `steps=[]`: executable checks are NOT_EXECUTED, not six demonstrated code regressions. Tests, Security, Docker, Lint and Docs workflows also report failure. Railway Deploy run 34268120322 is skipped. Billing was not investigated or changed, and no run was retried.

Main is unprotected; required status checks are empty. The sole returned ruleset `kelanatajox444` (13682266) is disabled. GitHub reports zero registered repository runners. Hosted-runner failure cannot be treated as proof a dedicated clean Linux validation runner exists. C04/C05 therefore remain blocked independently of source fixes.

Existing candidates inspected: owner-login `cd89ec55...` (main/candidate divergence 1/12), P1 recovery `e373bc7d...` (1/9), D1 composition `b2d02ff8...` (1/37), integration `a693386d...` (1/1). None is an ancestor of current main. A squash merge can include related changes without ancestry, so these counts do not establish missing functionality or justify a bulk cherry-pick.

## Railway: metadata, runtime and staged changes remain distinct

Project `af4d15d8-d4cb-44b7-80e7-d99a37ca0045`, production environment `5838964d-8c76-42b3-b0b9-18f2d1e4d5c2`, 20 services inventoried. Full sanitized config/deployment metadata is in `railway-services.json`; variable values and credentials were not requested. Long encoded provider start commands and registry credential fields were omitted from the persisted artifact.

Multiple live service configurations link to repository branch main, including API, engine, ingest, orchestrator, execution, pressure-outbox, BFF and worker services. The API schema returned no definitive autodeploy-enabled field, so `AUTO_DEPLOY_ENABLED=UNKNOWN`. A main push cannot be certified as having no provider consequences. GitHub's separate workflow_run release trigger also remains relevant.

Every service-config response reports shared staged patch `68c2214f-679f-4674-842d-fa052617e986`. This audit did not create, accept or modify that patch. An environment-wide accept could apply unrelated pending variable/config changes; a scoped reviewed deployment must reconcile that state first.

| Service | Latest provider deployment | Metadata / selected evidence |
|---|---|---|
| API | 81c42eb3-89f3-4876-bfe8-52e50b604bc1, SUCCESS, Sep 5 | Metadata has no source SHA/image. Sampled readiness HTTP200 is insufficient for fault or owner proof. |
| Orchestrator | 891df53a-8b9a-40ad-a60c-de91498833a7, SUCCESS, Sep 5 | Metadata commit 2c099aef...; sampled startup log says KILL_SWITCH / ACCOUNT_STATE_MISSING. |
| Frontend | bfc41a75-eaa7-48a9-a6c1-14e747399c2d, SUCCESS, Sep 6 | No commit/image in returned latest metadata; source parity and interactive acceptance unproven. |
| Pressure outbox | 069243e5-e5e2-4d52-bcec-cbc9a23e0c0b, SUCCESS, Sep 3 | Provider startCommand is a literal Markdown link to a Windows local script path. Effective executed command is unverified; review this override before next release. |
| Migrator | a82b28f0-5aa6-4e01-a7e1-fa452bc9d2f5, SUCCESS, Sep 3 | Source release/d0-demo-bbc3205b, checkSuites=false, metadata bbc3205b...; no direct applied schema proof collected. |
| Auditor | e5e24327-09f1-4c84-ab47-43f13913a52b, REMOVED | Image digest available, but this is not evidence an audit job is running or scheduled successfully. |

Limited logs were read from four selected exact deployments, filtered and sanitized. They are historical sampled runtime observations, not a current consistent cohort, database assessment, broker account proof or absence-of-errors proof.

## Bounded C01 implementation

Three files changed in the parent's isolated current-main worktree, without commit by this agent:

- `.github/workflows/railway-deploy.yml`: manual full SHA and CI run ID; exact checkout; production environment; no cancellation; four original valid service UUIDs; explicit project/environment; pinned Railway CLI 5.41.0; gate before provider credentials and again before upload; provider nonzero exits propagate. Nonexistent wolf15-worker removed without activating a replacement.
- `scripts/ci/railway_release_source_gate.py`: read-only GitHub receipt validation. Requires trusted repo/head-repo and ci.yml identity/path, current main matching checkout and requested SHA, completed successful matching attempt, every required job with real runner evidence, mandatory steps present and successful, no skipped/failed steps, a clean tracked/untracked checkout, and stable CI attempt after validation.
- `tests/test_railway_release_source_gate.py`: 42 fault/positive tests passed using `--noconftest`; Ruff lint and format passed; `git diff --check` passed. Fixtures cover tested-A/deploy-B substitution, fork/spoofed workflow, missing/failed/skipped evidence, no runner, absent migration and rerun race. This is scoped local evidence, not the repository's full required suite.

The helper executes repository source after checkout using only a read-only GitHub token; provider credentials are scoped to later steps. This is not a proof that arbitrary alternate workflows cannot access secrets. The existing canary workflow accepts arbitrary deploy/promote/rollback commands and cannot prove the resulting artifact from source SHA alone. C01 and C05 remain partial until that alternate release path is closed or separately bound to equivalent artifact evidence. Test-level pytest skips are not exposed as GitHub step skips; required-suite enforcement remains a separate C03 obligation.

## Milestone verdicts and next gates

A00 current source acquisition is refreshed. C01 is PATCHED_TESTED_LOCAL_PARTIAL. C02 has current source progress (API start script no longer forces embedded orchestrator) but no single-owner production proof. C03/C04/C05 are BLOCKED. Parent agent owns C06 changes and their testing. P1 ENGINEERING_DONE is not established.

P4 E01/E02/E03/E04/E05/E06/D01/E07/E08/E09 are not closed by this audit. Missing receipts include combined D0 source/build/EA include closure, mandatory disposable database and MetaEditor gates, actual applied production schema, explicit account/server/DEMO/reader binding, final SHADOW with zero submit, and one bounded independently reconciled engineering outcome. Provider SUCCESS never substitutes for these receipts. No broker fill was proven.

Before any production release: bind one tested combined commit/tree and image/config/schema/EA manifest; resolve alternate deployment and staged-provider state; establish exact-source CI/runner/review controls; prove affected migrations against the observed target head; verify ownership/readiness with fault receipts; and execute only the specifically bound rollout. Monitor source freshness, mandatory task health, queue progress and independent reconciliation on the selected artifact. Rollback must preserve ledger history and unknown exposure; blind downgrade/retry is not an acceptable recovery proof.

No push, merge, provider change, SSH session, database write, restart or broker action was executed by this agent. Safe-main-merge verdict: HOLD. Production release verdict: HOLD.
