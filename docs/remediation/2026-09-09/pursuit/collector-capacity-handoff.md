> Historical checkpoint: final validation and source commit subsequently completed; see collector-final-review.md and evidence/collector-final-validation.json. General host/runtime gates remain open.

# Collector validation capacity handoff

Pending base: c46b89bd4da2d965a507c67a7853db59b8a74a59, branch codex/s03-runtime-recovery-20260909. Preserve current source, tests and uncommitted pursuit evidence in this isolated worktree. Do not reset or discard it.

The first final-source attempt failed before pytest because Git could not allocate 1 MiB. A later lightweight counter read measured committed 18488389632 bytes / limit 19278962688 bytes, leaving 790573056 bytes (about 754 MiB). Available physical RAM was 4663 MiB; physical availability does not remove the commit-limit constraint. No host process, pagefile, VPS or workload was changed.

Current source hashes match the pending checkpoint and AST parsing succeeds. The cp1 test bytes can be reconstructed exactly by reversing only the import separator blank line; ASTs match. This supports a formatting-only delta but does not substitute for the requested final exact-byte test receipt. Native MCP cp1 remains 11 passed on its recorded bytes. cp2 has no collection/JUnit result.

Recovery package: provide independently verified adequate commit headroom on the existing host without stopping preserved workloads, or bind an authorized disposable testing host. Then run the same Native MCP environment and bounded suite, validate source stability and exact JUnit identities, review/stage hashes, and commit the scoped patch/evidence. No paid provisioning or host modification has been authorized by this handoff. No duplicate owner question is issued.

Remaining external gates are separate: PostgreSQL disposable acceptance and Linux evidence; GitHub account/required checks; Railway frontend branch-trigger verification before push; active DEMO account/EA/risk/canary/independent-reader binding. Solving host capacity alone does not close these gates. Milestones remain 0/6 and final goal is unchanged.
