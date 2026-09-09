# Codex interaction policy for WOLF15

## Work from current evidence

Confirm the repository, branch, exact base commit, effective entrypoint, and dirty
files before changing code. Preserve existing work; use an isolated worktree for
an independent change. Read the files relevant to the task before implementing.
Start architectural work with `docs/architecture/runtime-topology-current.md`,
`docs/architecture/authority-boundaries.md`, and the affected contracts and code.
Documentation records a claim; verify the implementation and date before relying
on it as runtime evidence.

## Choose a small set of relevant skills

Use the installed skill catalog with the repository assessment in
`docs/runbooks/codex-skill-assessment.md` and `.codex/skill-assessment.json`. Read a selected
skill's entrypoint before using it. Do not load the entire catalog into a task.

| Work | Preferred entrypoints | Repository anchors |
| --- | --- | --- |
| Locate an implementation or plan a change | `agent-scout-explorer`, `agent-planner` for requested planning | `docs/architecture/`, affected code and tests |
| Implement an authorized local fix | `agent-coder`, `agent-dev-backend-api` as needed | `api/`, `pipeline/`, `services/`, `tests/` |
| Review correctness and prove a change | `agent-reviewer`, `agent-tester`, `verification-quality` | focused tests and exact diff |
| Trace decisions and authority | `agent-reviewer`, `wolf15-authority-boundary-review` | `contracts/`, `constitution/`, `risk/`, `execution/` |
| Review authentication or dashboard containment | `agent-authentication`, a task-appropriate security skill | `dashboard/nextjs/`, `api/` |
| Audit historical strategy evidence | `wolf15-replay-audit` | `docs/strategy/`, `storage/`, replay tests |
| Assess production evidence | `agent-production-validator` | `deploy/`, runtime topology, read-only observations |
| Manage an explicitly requested PR | `agent-github-pr-manager` | exact PR head, review policy, CI evidence |

Core means relevant to normal repository work, not permission to run every core
skill automatically. Conditional skills require the matching task, actual tools,
and credentials where applicable. Use one primary workflow when generic routers
overlap. Delegate only independent bounded work when the task or governing
instructions call for it; do not start swarms just because skills are available.

Do not select out-of-scope or quarantined skills for this repository. This is an
instruction for the assistant, not a runtime disable or security boundary.
Project name-disable selectors loaded in config/read but did not disable skills
in the tested standalone skills/list; they are not relied upon. The installed
catalog remains available to other projects. Reassess the relevant entry if
the user brings that domain into this repository. Do not install a new platform,
replace the Next.js application with a hosted scaffold, or introduce Supabase,
AgentDB, Flow Nexus, or a V3 framework merely because a skill mentions it. Generic
PostgreSQL or JWT work does not establish a Supabase dependency.

Provider-key setup applies only to an explicitly API-backed task needing that
provider. Existing Codex access alone does not require a new API key. Document,
design, video, and cloud publication skills require the corresponding deliverable.

Thirteen assessed global packages reference missing local contracts/helpers and
are quarantined for this repository. Use the complete entrypoints in the routing
table rather than inventing those resources. The evaluator's mindmap collection
route also references a missing harness and collector; it is unavailable even
though other evaluator files exist. Restore and verify the actual package before
reenabling a quarantined route. Metadata lint is not a behavioral certificate.

## WOLF15 boundaries override generic workflow assumptions

- WOLF15's canonical pipeline owns trade decisions. A coding assistant, skill,
  score, model recommendation, memory, replay, or SHADOW result adds no verdict,
  risk reservation, command, EA, or broker authority.
- Pair admission opens its specified analysis scope only. Preserve risk vetoes,
  closed-candle lineage, freshness, expiry, idempotency, and kill-switch checks in
  affected code. Do not invent missing account, risk, candle, or execution data.
- The selected dashboard is a read-only viewer with bounded server-side calls to
  the core API. It does not approve exposure or lot size. The legacy BFF is not a
  fallback for the selected frontend. Verify current topology before any change.
- The installed `audit-wolf15-constitution` text contains a legacy combined
  "Risk/Dashboard" owner. Do not apply that claim to the current system. Use the
  current authority contracts and `wolf15-authority-boundary-review`; treat the
  legacy skill as a source under review, never as authority to grant dashboard
  risk or execution permissions.
- Research, observers, learning, and journals do not become alternate writers.
  Preserve SHADOW and no-self-promotion boundaries where the task touches them.

## Match actions to the user's actual authorization

Complete authorized local implementation, inspection, and proportionate tests.
Honor authorization already given in the task; do not repeatedly ask for it.
Production mutations, provider changes, deployments, migrations, broker actions,
external publication, and messages require task-specific authorization. A skill
trigger, test result, or command rule is not that authorization. Bind any supplied
one-shot authorization to its exact target and window; do not retry or broaden it.

Never print secrets. Prefer structured tools for scoped reads. Production database
observation uses the established auditor role and read-only transactions; do not
substitute an administrator credential. Do not run broad test selections with
production endpoints or credentials. Verify fixtures and isolate external effects.

`.codex/rules/` contains command-review prompts, not skill permissions or a complete
security boundary. Host sandbox, managed policy, credentials, and service controls
remain separate. Do not rely on AGENTS.md to enforce network or broker isolation.

## Verify and report precisely

Choose tests from actual affected files; distinguish static validation, local test
results, remote CI, deployment identity, runtime/database evidence, and direct
broker evidence. Preserve UNKNOWN, NOT_MEASURED, NOT_EXECUTED, HOLD, and NO-SHIP.
A job with no runner or steps did not execute. Keep static skill fit, metadata
lint, and formal behavioral evaluation separate; do not manufacture quality scores
or authenticated evaluator evidence. A formal evaluator cannot grant action
authority.

Report the exact changes, verification, and remaining gaps. Use task artifacts for
the assessment trail. Global memory writes require an explicit user request and
the configured memory-update mechanism; generic skill writeback advice does not
grant that permission.
