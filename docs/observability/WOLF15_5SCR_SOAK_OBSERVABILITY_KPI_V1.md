# Wolf15 5S-CR Soak Observability KPI V1

Document ID: WOLF15_5SCR_SOAK_OBSERVABILITY_KPI_V1

This contract defines read-only evidence for the Lifecycle V2 writer and the
later Shadow Evidence V2 soak. It does not grant analysis, risk, command, DEMO,
LIVE, or broker authority.

## Current rollout boundary

The current acceptance sequence is:

    natural post-cutover PairAdmissionV2
    -> one durable Lifecycle V2 admission link
    -> one Lifecycle V2 identity
    -> at most one logical evidence job
    -> restart pressure-outbox
    -> identity and lineage remain stable
    -> only then consider Shadow Evidence V2 activation

An empty observation window is NO_OPPORTUNITY, not proof that the live writer
path passed.

## Metric namespaces

Metric names identify their source and semantics:

| Namespace | Meaning |
| --- | --- |
| db_audit.* | Current-state PostgreSQL gauge or count reconstructed by a read-only query. |
| derived_ratio.* | Ratio derived from durable facts; never a monotonic counter. |
| restart_comparison.* | Difference between operator-captured before/after documents. |
| runtime_counter.* | Process-local blocked/rejected attempt counter; not implemented in V1. |

Do not use lifecycle IDs, event IDs, payload hashes, command IDs, or account
identifiers as Prometheus labels. A future reason_code label must use a fixed
allowlist and must never contain raw exception text.

## Writer-only metrics

The cutover watermark is mandatory input:

    writer_enabled_at_utc
    writer_deployment_id
    writer_commit_sha
    minimum_admission_time_utc

### Primary funnel

| Metric | Definition | Gate |
| --- | --- | --- |
| db_audit.eligible_delivered_admission_count | Distinct valid PairAdmission IDs in the durable inbox at or after the watermark. | Informational. Zero means NO_OPPORTUNITY. |
| db_audit.admission_link_count | Admission links whose admitted_at is at or after the watermark. | Equal to eligible delivered admissions after the writer has polled. |
| db_audit.unlinked_eligible_admission_count | Eligible durable-inbox admissions with no V2 admission link. | 0 at acceptance capture. |
| db_audit.orphan_admission_count | Admission links missing either their lifecycle or pressure-event link. | 0. |
| db_audit.evidence_job_count | Evidence jobs belonging to post-cutover admission links. | At most one per admitted lifecycle. |
| db_audit.duplicate_admission_row_count | Duplicate persisted admission identities. | 0; database-state corruption guard. |
| db_audit.duplicate_logical_job_row_count | More than one persisted job for one lifecycle identity. | 0; database-state corruption guard. |

The duplicate metrics above do not count blocked attempts. Their future runtime
counterparts are separate and may legitimately be greater than zero:

    runtime_counter.admission_link_conflict_blocked_total
    runtime_counter.duplicate_job_attempt_blocked_total

### Lifecycle diagnostics

Keep these two definitions separate:

    derived_ratio.legacy_to_v2_lifecycle_ratio
    = distinct transport lifecycle IDs / distinct V2 lifecycle IDs

    derived_ratio.events_per_v2_lifecycle
    = linked pressure events / distinct V2 lifecycle IDs

The first compares grouping models. The second measures episode depth. Neither
has a universal higher-is-better target. Review by symbol, rule version,
deployment, session, and market regime when those dimensions are available.

clean_blocks_per_v2_lifecycle is also diagnostic. Active lifecycles are rows in
ANALYSIS_OPEN or TRANSITION_PENDING.

## Shadow Evidence V2 metrics

These become acceptance metrics only after writer restart parity passes and the
Shadow Evidence V2 worker is deliberately activated.

| Metric | Gate |
| --- | --- |
| db_audit.evidence_snapshot_count | One per logical completed job. |
| db_audit.completed_job_without_snapshot_count | 0. This is not full restart parity. |
| db_audit.forming_candle_used_count | 0. |
| db_audit.future_candle_used_count | 0. |
| db_audit.unexplained_comparison_difference_count | 0. |
| db_audit.valid_for_execution_true_count | 0. |
| db_audit.execution_authority_true_count | 0. |
| restart_comparison.decision_time_drift_count | 0. |
| restart_comparison.context_hash_drift_count | 0. |
| restart_comparison.evidence_hash_drift_count | 0. |

comparison_difference_with_reason_count is diagnostic and may be greater than
zero. It is not an authority violation.

price_coverage_from_block_start_pct is NOT_MEASURABLE_YET: the schema does not
store expected active-market seconds, covered active-market seconds, and
coverage gaps from block_started_at to decision_time.

waiting_evidence_age_seconds can be measured as wall time, but an SLA gate is
NOT_MEASURABLE_YET until the audit can calculate provider-calendar active
market time. Weekend and market closure must not count as deadlock time.

## Restart comparison

Capture one admitted lifecycle immediately before and after restarting only the
pressure-outbox service. Compare:

    strategy_lifecycle_id
    admission_event_id
    pressure_event_id
    raw_lineage_hash
    evidence_job_id
    decision_time
    material_state_hash
    context_hash
    evidence_hash

Also compare each execution-plane table independently:

    risk_reservation_row_count
    final_signal_outbox_row_count
    execution_command_row_count
    execution_report_row_count
    broker_order_row_count
    broker_deal_row_count
    broker_position_row_count

Every before/after delta must be zero. Never collapse these values into one
aggregate because opposite changes could cancel each other.

## Prometheus boundary

Prometheus metric names may be designed now, but the Lifecycle V2 worker has no
runtime exporter. Its registry is process-local and cannot be observed through
the API process /metrics endpoint.

    KPI naming contract                 = GO
    read-only PostgreSQL audit          = GO
    pressure-outbox Prometheus exporter = HOLD
    observability migration             = NO-GO

A future instrumentation PR may choose a dedicated worker metrics endpoint, a
read-only PostgreSQL collector, or OpenTelemetry. It must not change Lifecycle
V2 flags or execution authority.

## Deferred subsystems

Microboost has a transition contract and pure reducer, but no durable pulse
repository, production consumer, restart recovery, or authoritative conversion
denominator. ContextEpoch is not a durable subsystem. Their operational KPIs
remain HOLD.

Candidate V2, the structural solver, automatic C2/C3 wiring, DEMO, and LIVE
metrics also remain outside this contract. The existing operator-controlled C3
SHADOW capability is not a scheduler or runtime activation.

## Phase-gated productivity funnel

The intended analysis model is episode-centric, pulse-aware, structural, and
target-first. It preserves modern lineage and safety contracts; it does not
restore an old log schema or treat every pressure emission as a new decision.

The future funnel is:

    eligible admission
    -> durable lifecycle
    -> independent pulse formed
    -> material context resolved
    -> immutable thesis opened
    -> closed H1 confirmed
    -> ordered M15 confirmed
    -> feasible entry domain solved
    -> Candidate V2 or terminal NO_TRADE

Productivity means an admitted episode reaches a deterministic terminal
analysis result. It does not mean maximizing raw signal or broker-order count.

Each stage must remain NOT_MEASURABLE_YET until its authoritative durable owner
exists. Do not report a missing subsystem as zero conversion:

| Funnel stage | Current authoritative source | Current status |
| --- | --- | --- |
| eligible admission | durable inbox plus cutover watermark | Measurable now. |
| durable lifecycle | Lifecycle V2 admission and event links | Measurable now. |
| independent pulse formed | none; reducer is process-local and unconsumed | NOT_MEASURABLE_YET. |
| material context resolved | none; context_epoch_id is not a durable subsystem | NOT_MEASURABLE_YET. |
| immutable thesis opened | no DirectionalThesis owner | NOT_MEASURABLE_YET. |
| closed H1 confirmed | legacy evidence exists, but not Lifecycle V2 analysis authority | NOT_MEASURABLE_YET for the V2 funnel. |
| ordered M15 confirmed | legacy evidence exists, but not Lifecycle V2 analysis authority | NOT_MEASURABLE_YET for the V2 funnel. |
| feasible entry domain solved | no route-aware interval solver | NOT_MEASURABLE_YET. |
| Candidate V2 or terminal NO_TRADE | no authoritative Candidate V2 path | NOT_MEASURABLE_YET. |

When those owners exist, conversion denominators must use admitted lifecycle
cohorts that are mature or terminal. A lifecycle still waiting for evidence is
not a conversion failure.

Future safety gates remain:

    admission_without_lifecycle_count                 = 0
    sticky_state_promoted_to_false_pulse_count        = 0
    false_material_context_epoch_count                = 0
    future_candle_authority_violation_count           = 0
    candidate_without_ordered_h1_m15_proof_count      = 0
    candidate_below_10pip_floor_count                 = 0
    candidate_below_1_5_rr_count                      = 0

Blocked or rejected attempts are diagnostic counters and may be greater than
zero. Only authority violations are hard zero gates.

## Authority rollout order

This KPI contract does not authorize the following roadmap. It only fixes the
measurement boundary and order:

1. Complete the writer-only natural-admission and restart proof.
2. Run Shadow Evidence V2 soak with no execution authority.
3. Review a separate proposal to make Lifecycle V2 the selected analysis owner.
4. Add durable Microboost transition ownership.
5. Add material ContextEpoch and immutable directional thesis ownership.
6. Add ordered structural proof and a route-aware feasible-entry solver.
7. Add Candidate V2 target-first policy, selecting FX_MIN_TARGET_10P_V1 only on
   the new path.

Legacy grouping, its six-pip replay policy, C2/C3 activation, EA code, DEMO, and
LIVE remain unchanged throughout the current writer-only gate.

## Acceptance status

The writer-only audit returns:

    NO_OPPORTUNITY  no eligible post-cutover admission was observed and safety gates are clean
    PASS            at least one eligible admission was observed and all applicable gates passed
    FAIL            one or more safety or lineage gates failed

No result from this package authorizes Shadow Evidence V2, C2/C3 activation,
DEMO, LIVE, or broker execution.

## Operator usage

All database commands require DATABASE_URL and execute in a repeatable-read,
read-only transaction. Use the deployed commit, migration, and cutover values;
do not infer them from the local checkout.

Capture the current writer-only state:

    python -m scripts.audit_5scr_writer_only snapshot \
      --manifest docs/observability/5scr_writer_only_manifest.json \
      --output writer-only-snapshot.json

After the first natural admission, capture before restart:

    python -m scripts.audit_5scr_writer_only capture \
      --phase before \
      --admission-event-id <5scr-admission-id> \
      --manifest docs/observability/5scr_writer_only_manifest.json \
      --output restart-before.json

Restart only pressure-outbox, then repeat with phase after and output
restart-after.json. Compare without database access:

    python -m scripts.audit_5scr_writer_only compare \
      --before restart-before.json \
      --after restart-after.json \
      --output restart-comparison.json

The compare command exits non-zero when identity, lineage, metadata, or any
individual execution-plane row count drifts.
