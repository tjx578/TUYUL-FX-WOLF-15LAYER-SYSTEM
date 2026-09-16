-- WOLF15_5SCR_RESTART_CAPTURE_BEFORE_V1
-- Parameter $1: admission_event_id (text)
-- Parameter $2: minimum_admission_time_utc (timestamptz)
-- Capture exactly one logical admission before restarting pressure-outbox.

SELECT
    admission.admission_event_id,
    admission.strategy_lifecycle_id,
    admission.pressure_event_id,
    admission.raw_lineage_hash,
    admission.admission_rule_version,
    admission.admitted_at,
    admission.linked_at,
    lifecycle.symbol,
    lifecycle.state AS lifecycle_state,
    lifecycle.direction_state,
    lifecycle.rule_version AS lifecycle_rule_version,
    lifecycle.material_state_hash,
    lifecycle.event_count,
    lifecycle.clean_block_count,
    job.evidence_job_id,
    job.status AS evidence_job_status,
    job.decision_time,
    snapshot.snapshot_id,
    snapshot.context_hash,
    snapshot.evidence_hash
FROM strategy_5scr_lifecycle_admission_links_v2 AS admission
JOIN strategy_5scr_analysis_lifecycles_v2 AS lifecycle
  ON lifecycle.strategy_lifecycle_id = admission.strategy_lifecycle_id
LEFT JOIN strategy_5scr_evidence_jobs_v2 AS job
  ON job.admission_event_id = admission.admission_event_id
LEFT JOIN strategy_5scr_evidence_snapshots_v2 AS snapshot
  ON snapshot.evidence_job_id = job.evidence_job_id
WHERE admission.admission_event_id = $1::text
  AND admission.admitted_at >= $2::timestamptz;
