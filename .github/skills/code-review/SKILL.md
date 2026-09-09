---
name: agent-analyze-code-quality
description: >-
  Assess maintainability, correctness risks, complexity, and consistency in a scoped codebase. Use when the user requests a code-quality assessment rather than a security-only or performance-only scan.
---

# Agent Analyze Code Quality

Use this skill to assess maintainability, correctness risks, complexity, and consistency in a scoped codebase.

## Applicability

Apply it when the user requests a code-quality assessment rather than a security-only or performance-only scan. Keep adjacent concerns in their own workflow unless they are necessary to this objective.

## Domain checks

- Verify that the result explicitly covers prioritized findings with locations, evidence, impact, and focused improvements.
- Exercise or reason through at least one failure, ambiguity, or unavailable-evidence case specific to this trigger: the user requests a code-quality assessment rather than a security-only or performance-only scan.
- Explain how current evidence supports the selected approach to assess maintainability, correctness risks, complexity, and consistency in a scoped codebase.

## Workflow

1. Establish the review scope, intended behavior, relevant standards, and available evidence.
2. Trace important behavior through code and configuration instead of relying on names or comments.
3. Separate proven defects, maintainability concerns, and unverified hypotheses.
4. Prioritize findings by realistic impact, likelihood, and remediation cost.
5. Check the proposed conclusions for false positives and summarize readiness without making edits.

## Safety and scope

- A review request is read-only unless the user separately requests fixes.
- Do not report style preferences as correctness defects.
- Do not infer production behavior from local static evidence alone.
- Do not convert subjective style preferences into defects or automatically rewrite reviewed code.
- Use only tools and dependencies confirmed available in the current environment; otherwise provide a plan and label execution NOT_EXECUTED.

## Output

Return prioritized findings with locations, evidence, impact, and focused improvements. Include evidence used, material assumptions, checks not executed, remaining risks, and the next authorized action.

## Core Evaluator v2 integration

Before treating this skill as locally ready for installation, merge, or release, use `$evaluate-agent-skill` on a private bundle of the exact canonical package bytes with bundled profile `common-skill/v1`. The evaluator consumes pre-collected evidence; it does not run this skill, its tests, scanners, Git, or external actions.

Require fresh structured evidence bound to the same run ID, revision, subject tree digest, and exact collector `id@version`. If the evaluator, profile, collector, evidence, or binding cannot be exercised, report `NOT_EXECUTED` or `NOT_MEASURED`; never infer `PASS_LOCAL`. A `PASS_LOCAL` verdict applies only to the observed local bytes and leaves merge, publish, deploy, rollback, runtime mutation, memory write, and broker execution authority `false`.
