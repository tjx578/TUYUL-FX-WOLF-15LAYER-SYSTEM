# D1 release composition candidate

This isolated composition starts at e373bc7d105031b32c8054b881097869ceec2f61, tree bb5d633e96bab8350e4db5573c23a6664fa99326. It preserves c64 orchestrator single ownership, fencing, recovery and real process-restart test, and adds strict closed-candle drift, analysis admission and the complete D0 canary dependency set. It does not activate execution or grant strategy/DEMO authority.

## Inputs and resolutions

- a693386d43848ce97baa14b5d43d52d6f7ecfb78: full 25-path strict drift and shadow admission change. This was a sibling of c64, not its replacement. Applied without textual conflicts.
- D0 input b17887c9d901af3248a2c645d6da3f69e584c07b and recovery repair ba3d250a11beb8fcdda3faeb16a0e07d874b652f were read from the local D0 repository. No network fetch or remote branch update was required.
- D0 feature commits selected in dependency order: 3ee17b8c1fa94ca74bf57f3d0027172b684ddad2, bca6408d49ac9ca8f6cc8f9eac62e2c9ff7af43d, 3f4b8293c6c70b010bbbb85306379ba54079e125, 8880b1dc5189ff22aba6650f052353d6e1769dd4, 132a428106bcc9e9c3e4303f48d6075a77b8a6ab, 751a9694bc7eff1e3e6b1d20405a840066d478bf, b17887c9d901af3248a2c645d6da3f69e584c07b, ba3d250a11beb8fcdda3faeb16a0e07d874b652f. All applied without textual conflicts.
- This includes protocol validation, command repository and governance, exact authority packets, direct broker reconciliation ledgers/repository, API governance wiring, migrations, issue/record scripts, EA Demo and Shadow credential transport, Windows credential broker source, and tests. MQ5 was not transplanted alone.
- Relevant test dependency 2c250ac195db6944196501c40f1242bd2053af4e restores the bridge-governance singleton exactly after PostgreSQL tests. The stale startup-migration test was replaced with its exact ba3 version, which verifies the existing redacting migration runner and error propagation. No runner behavior was changed.
- Other D0-branch G3/forensic/performance/fixture work was not pulled wholesale. All selected D0 product paths equal ba3 after composition. Existing standalone ownership code remains present, and advisory admission retains execution_authority=false.
- Two independent Alembic heads were present after composition: 20260826_01 (admission) and 20260905_01 (D0). Additive merge revision 20260908_01 requires both and has no DDL. Historical migrations and their parent links are unchanged.

## Validation and evidence limits

Actual PostgreSQL 17 disposable migrations passed from each pre-merge head and from an empty database to 20260908_01, with required admission and D0 tables verified. The selected D0 governance, command and canonical observer database tests passed 28/28. No production database or broker was contacted.

Focused ownership/recovery/health/startup/drift/admission/D0 suite: 422 passed and 2 failed initially. The failures were an incorrect test-only Alembic traversal option and a pre-existing stale migrator assertion; the repaired test files passed all 5 cases. Application source did not change after the successful 422 cases or the PostgreSQL run. Earlier failures remain in evidence. Real process-recovery cases passed on the composed source.

T14 exact image/entrypoint validation and resulting commit/tree bindings are recorded in the external release-composition receipt. No image or runtime verdict is implied by this document. R01-R08 remain production runtime gates; P3 installation/SHADOW, P4 D0 transaction, P5 natural handoff and strategy authority, and P6 automatic window remain separate.

Evidence directory: C:/Users/INTEL/.codex/visualizations/2026/09/07/01a079d8-179a-7301-8236-ba92019a6079/goal-six-packages/release-composition.

Original main, c64, a693 and D0 candidate worktrees are preserved. No push, shared merge, deployment, production migration, installed EA change, or broker action is performed by this composition.
