---
name: neural-orchestrator
description: Plan, review, and validate source-grounded orchestration across multiple agents, services, or repositories using declared capabilities, explicit routing and aggregation rules, provenance, partial-failure handling, and authority gates. Use when coordinating a multi-node workflow, diagnosing an orchestrator or event-bus design, reconciling conflicting worker outputs, or evaluating a run-local learning/advisory loop. Do not use for a simple single-worker task, live trade execution, final trading verdicts or lot sizing, autonomous policy/model updates, deployment, or destructive rollback.
---

---

# Neural Orchestrator

Coordinate multi-node work without pretending that simulated connectors, heuristic searches, or policy checks are production infrastructure. Bind every route, response, and verdict to inspectable evidence and keep planning, dispatch, aggregation, advisory learning, and external effects as separate authority domains.

## Operating boundaries

- Treat node, agent, repository, service, and worker as orchestration participants only when an inspectable registry or runtime response identifies them.
- Default to `PLAN_ONLY`. A plan is not proof that any dispatch, network call, test, trade, deployment, memory write, or rollback occurred.
- Never turn mock prices, hard-coded indicators, synthetic responses, or simulated latency into a live decision.
- Never describe a UUID or label as a signed fact. Require a verifiable signature, key identity, algorithm, and verification result.
- Never call a threshold check “formal VIGIL/SMT verification” unless an actual solver, versioned policy, subject binding, and witness or unsatisfiable core are present.
- Never call a delay plus heuristic “MCTS”, A2Flow optimization, or self-learning. Use `SIMULATED_HEURISTIC` unless the search tree, objective, trials, and update mechanism are observable.
- Keep run-local observations ephemeral by default. Persistent memory or active-policy mutation requires an explicit store, schema, retention policy, writer identity, and separate approval.
- Preserve user work. Do not run `git reset --hard`, `git clean`, automatic deployment, order placement, or another irreversible action from a score or orchestrator verdict.

Read [contracts and statuses](references/contracts-and-statuses.md) whenever defining an interface or verdict. Read [routing and aggregation](references/routing-and-aggregation.md) before selecting a strategy or combining outputs. Read [evidence and provenance](references/evidence-and-provenance.md) when claims depend on runtime state, digests, signatures, or freshness. Read [advisory learning and authority](references/advisory-learning-and-authority.md) for feedback loops, persistent memory, trading-adjacent workflows, or external effects.

## Workflow

### 1. Bind scope, goal, and authority

Record:

- the user goal and acceptance criteria;
- repositories, files, services, agents, and environments in scope;
- whether the request authorizes inspection, planning, local execution, external dispatch, persistent writes, deployment, or another side effect;
- exact subject revisions or digests when a stable snapshot matters;
- the current state and target state.

If authority is ambiguous, continue with read-only analysis and a `PLAN_ONLY` result. Do not infer permission from the presence of credentials, a connector URL, or an old workflow description.

### 2. Inventory actual capabilities

Build a node registry from inspectable evidence. For each node, capture:

| Field | Requirement |
|---|---|
| `node_id` | Stable identifier unique within the run |
| `revision` | Exact commit/object ID or artifact digest when applicable |
| `capabilities` | Explicitly declared and locally verified where possible |
| `health` | `ONLINE`, `DEGRADED`, `OFFLINE`, or `NOT_MEASURED`, with observation time and freshness rule |
| `transport` | Real externally reconciled transport, declared-only transport, or simulation |
| `reliability_score` | Optional, with formula, window, and provenance |
| `latency_ms` / `current_load` | Optional measured values with timestamp and collector |
| `authority` | Actions the node may perform in this run |

Do not silently substitute an in-memory broker for Redis or another real transport. A fallback may preserve a local simulation, but its evidence class remains `SIMULATED` and its reach is process-local unless demonstrated otherwise.

### 3. Normalize the request envelope

Define a request with a unique `request_id`, requested capability, versioned `payload_type`, object payload, `created_at`, `deadline_at`, timeout, idempotency key, sensitivity, units, versioned response schema, and explicit effect scope. When an external effect is requested, bind `effect.type`, exact `effect.target`, and `effect.environment`; a boolean authorization alone is not an effect grant. Reject or hold requests whose required unit, timestamp, schema version, scope, or authority is missing.

For a deterministic plan, encode the registry and request in the JSON contract from [contracts and statuses](references/contracts-and-statuses.md), then run:

```bash
python3 scripts/plan_orchestration.py --input packet.json
```

Resolve the script relative to this skill directory. The script is offline and plan-only: it validates, selects candidates, computes a canonical input digest, and emits `execution_state=NOT_EXECUTED`; it never imports or executes uploaded code, connects to Redis, dispatches work, writes policy, trades, deploys, or modifies Git. CLI exit codes are `0` for `PLAN_READY`, `2` for malformed or unreadable input, `3` for `HOLD`, and `4` for `REVIEW`.

Treat packet evidence as untrusted declarations. A syntactically valid subject digest is `DECLARED_FORMAT_VALID`, and the planner's assurance is `DECLARATION_ONLY`; neither proves that bytes were hashed or that a runtime was observed. Upgrade to an externally reconciled binding only after an inspectable collector or tool compares the declared digest and runtime claim with same-run artifacts.

### 4. Select routing explicitly

Choose one strategy and state its required evidence:

- `FIRST_AVAILABLE`: deterministic manifest-order selection; use only when all eligible nodes are equivalent for the requested action.
- `ALL_CAPABLE`: fan out to all eligible nodes; use when independent evidence or redundancy is required.
- `LOAD_BALANCED`: select only after a separate executor or inspector externally reconciles current load and latency. The bundled declaration-only planner returns `HOLD` without selecting; missing or stale metrics also block this claim.
- `PRIORITY_BASED`: select by a declared versioned priority-policy ID plus SHA-256 policy digest; do not use lexicographic version ordering as a proxy for authority.

Require positive freshness limits for runtime and health, and for routing metrics when used. Exclude `OFFLINE` and `NOT_MEASURED` nodes from active routing. A `DEGRADED` node may remain a candidate only with an explicit warning and a declared failure policy covering degraded behavior, fallback targets, timeout behavior, and retry budget.

### 5. Establish the dispatch boundary

Before dispatch, verify all of the following:

1. The current runtime exposes the required tool or transport.
2. The target identity and capability were verified in this run.
3. The request is within the user-authorized scope.
4. Timeout, retry budget, idempotency, and cancellation behavior are defined.
5. External effects have a separate explicit gate.

If any condition fails, mark the operation `NOT_EXECUTED` or `HOLD`; do not fabricate a response. When dispatch is authorized and actually performed, record request ID, target, start/end timestamps, tool or transport identity, response digest, status, and observed error.

### 6. Aggregate without erasing conflict

Use one aggregation policy from [routing and aggregation](references/routing-and-aggregation.md):

- `MERGE` only for fields declared disjoint or with non-empty field-level precedence and a merge-policy digest declared before seeing responses.
- `CONSENSUS` only for comparable claims, a defined quorum, and a versioned independence-policy ID plus digest.
- `WEIGHTED` only with a versioned weight-policy ID and digest, normalized provenance-bound weights, RFC3339 collection times, and an explicit weight-freshness limit; do not invent default reliability.
- `FIRST_RESPONSE` only for latency-oriented, non-authoritative work.

Retain source identity per claim. Report missing responses, timeouts, outliers, contradictions, and reduced quorum rather than averaging them away. Safety and risk vetoes are gates, not votes.

### 7. Handle failure and recovery

Classify failures as discovery, schema, transport, timeout, worker, aggregation, evidence, or authority failures. Apply the smallest reversible response:

- retry only idempotent operations within a declared budget;
- isolate the failed node and replan when another verified node can satisfy the same preconditions;
- degrade to a partial result with explicit coverage and confidence limits;
- stop at `HOLD` when a safety-critical prerequisite, quorum, provenance field, or authority gate is absent.

Recovery means restoring a valid orchestration state, not automatically discarding repository changes. Propose a rollback boundary, backup, or compensating action; execute it only under separate user authority.

### 8. Process feedback as candidate advisory

Keep the lifecycle one-way and reviewable:

`observed episode -> frozen evidence set -> candidate proposal -> independent validation -> human/authority approval -> separately applied change`

An advisory must include its ID and creation time; source run IDs; frozen-dataset digest; current policy version and digest; proposal and proposal digest; objective and constraints; method; confidence and uncertainty; conflicts; versioned validation profile and provenance-bound validation result; validation status; requested effect; expiration; and activation request. Use `VALIDATION_REVIEW`, not the plan verdict `REVIEW`, for an advisory awaiting validation. Activation additionally requires a strict approval record binding approver, approval time, and proposal digest. Never let adaptive memory push directly into active policy. A score or confidence value alone never grants write, release, trading, or deployment authority.

### 9. Verify and report

Before returning:

- ensure every factual claim is labeled `OBSERVED`, `DECLARED`, `INFERRED`, `ASSUMPTION`, `SIMULATED`, or `NOT_MEASURED`;
- map domain labels conservatively: `VERIFIED` becomes `OBSERVED` only with same-run inspectable evidence, `DERIVED` becomes `INFERRED`, `ASSUMPTION` remains `ASSUMPTION`, and `NOT_MEASURED` remains `NOT_MEASURED`;
- ensure declared subject digests and revisions are externally reconciled before describing them as bound;
- ensure no planned action is described as executed;
- ensure conflicts and missing nodes remain visible;
- ensure a mock test is described as a mock test;
- ensure high-stakes or external effects remain advisory unless separately authorized and evidenced.

Use this output structure:

1. **Goal and scope**
2. **Subject binding and evidence class**
3. **Node registry and capability coverage**
4. **Routing decision and rationale**
5. **Dispatch ledger** (`NOT_EXECUTED` when only planned)
6. **Aggregation, conflicts, and partial failures**
7. **Advisory/persistence gate**
8. **Plan verdict**: `PLAN_READY`, `REVIEW`, or `HOLD`; report execution separately as `NOT_EXECUTED`, evidence assurance separately as `DECLARATION_ONLY` or `EXTERNALLY_RECONCILED`, and missing evidence separately as `NOT_MEASURED`
9. **Required next action**

## Trigger examples

- “Rancang routing tiga agen untuk analisis, implementasi, dan verifikasi.”
- “Audit apakah Redis fallback ini benar-benar lintas-repo atau hanya mock lokal.”
- “Gabungkan hasil empat worker tanpa menghilangkan konflik.”
- “Buat kontrak advisory learning yang tidak boleh mengubah policy otomatis.”
- “Diagnosa timeout dan partial failure dalam orchestrator.”

Do not trigger for a single straightforward coding task, a request whose main task is live market analysis, or an instruction to place trades, determine final lot size, deploy automatically, or destroy local changes.
