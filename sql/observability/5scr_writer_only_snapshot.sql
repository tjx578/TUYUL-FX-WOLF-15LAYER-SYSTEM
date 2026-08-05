-- WOLF15_5SCR_WRITER_ONLY_SNAPSHOT_V1
-- Parameter $1: minimum_admission_time_utc (timestamptz)
-- Single read-only statement. No temporary objects or session mutation.

WITH eligible_delivered AS (
    SELECT DISTINCT
           o.payload ->> 'pair_admission_id' AS admission_event_id,
           o.event_id::text AS pressure_event_id
    FROM strategy_5scr_inbox AS inbox
    JOIN pressure_outbox AS o ON o.event_id = inbox.event_id
    WHERE o.signal_valid_at >= $1::timestamptz
      AND o.payload ->> 'pair_admission_status' = 'GRANTED'
      AND o.payload ->> 'radar_status' = 'ANALYSIS_READY'
      AND o.payload ->> 'pressure_selection_confirmed' = 'true'
      AND o.payload ->> 'pair_admission_id' ~ '^5scr-admission:[0-9a-f]{32}$'
),
post_cutover_admissions AS (
    SELECT *
    FROM strategy_5scr_lifecycle_admission_links_v2
    WHERE admitted_at >= $1::timestamptz
),
post_cutover_lifecycles AS (
    SELECT DISTINCT strategy_lifecycle_id
    FROM post_cutover_admissions
),
event_depth AS (
    SELECT links.strategy_lifecycle_id,
           count(*)::bigint AS event_count,
           count(DISTINCT links.source_clean_block_id)
               FILTER (WHERE links.source_clean_block_id IS NOT NULL)::bigint AS clean_block_count
    FROM strategy_5scr_lifecycle_event_links_v2 AS links
    JOIN post_cutover_lifecycles AS lifecycle
      ON lifecycle.strategy_lifecycle_id = links.strategy_lifecycle_id
    GROUP BY links.strategy_lifecycle_id
),
duplicate_admissions AS (
    SELECT admission_event_id
    FROM strategy_5scr_lifecycle_admission_links_v2
    GROUP BY admission_event_id
    HAVING count(*) > 1
),
duplicate_jobs AS (
    SELECT strategy_lifecycle_id
    FROM strategy_5scr_evidence_jobs_v2
    GROUP BY strategy_lifecycle_id
    HAVING count(*) > 1
),
unexplained_comparisons AS (
    SELECT comparison_id
    FROM strategy_5scr_evidence_comparisons_v2
    WHERE (
        same_lifecycle_grouping IS NOT TRUE
        OR same_candle_set IS NOT TRUE
        OR same_context_hash IS NOT TRUE
        OR same_terminal_reason IS NOT TRUE
        OR same_trade_geometry IS NOT TRUE
    )
      AND reason_codes = '[]'::jsonb
),
authority_violations AS (
    SELECT
        (SELECT count(*) FROM strategy_5scr_analysis_lifecycles_v2 WHERE execution_authority)::bigint
      + (SELECT count(*) FROM strategy_5scr_lifecycle_admission_links_v2 WHERE execution_authority)::bigint
      + (SELECT count(*) FROM strategy_5scr_evidence_snapshots_v2 WHERE execution_authority)::bigint
      + (SELECT count(*) FROM strategy_5scr_evidence_comparisons_v2 WHERE execution_authority)::bigint
        AS violation_count
),
broker_counts AS (
    SELECT
        count(*) FILTER (WHERE entity_type = 'ORDER')::bigint AS broker_order_count,
        count(*) FILTER (WHERE entity_type = 'DEAL')::bigint AS broker_deal_count,
        count(*) FILTER (WHERE entity_type = 'POSITION')::bigint AS broker_position_count
    FROM broker_entities
)
SELECT
    (SELECT count(*) FROM eligible_delivered)::bigint AS eligible_delivered_admission_count,
    (SELECT count(*) FROM post_cutover_admissions)::bigint AS admission_link_count,
    (SELECT count(*)
       FROM eligible_delivered AS eligible
       LEFT JOIN post_cutover_admissions AS admission
         ON admission.admission_event_id = eligible.admission_event_id
      WHERE admission.admission_event_id IS NULL)::bigint AS unlinked_eligible_admission_count,
    (SELECT count(*)
       FROM post_cutover_admissions AS admission
       LEFT JOIN strategy_5scr_analysis_lifecycles_v2 AS lifecycle
         ON lifecycle.strategy_lifecycle_id = admission.strategy_lifecycle_id
       LEFT JOIN strategy_5scr_lifecycle_event_links_v2 AS event_link
         ON event_link.pressure_event_id = admission.pressure_event_id
      WHERE lifecycle.strategy_lifecycle_id IS NULL
         OR event_link.pressure_event_id IS NULL)::bigint AS orphan_admission_count,
    (SELECT count(*)
       FROM strategy_5scr_evidence_jobs_v2 AS job
       JOIN post_cutover_admissions AS admission
         ON admission.admission_event_id = job.admission_event_id)::bigint AS evidence_job_count,
    (SELECT count(*)
       FROM strategy_5scr_evidence_snapshots_v2 AS snapshot
       JOIN strategy_5scr_evidence_jobs_v2 AS job
         ON job.evidence_job_id = snapshot.evidence_job_id
       JOIN post_cutover_admissions AS admission
         ON admission.admission_event_id = job.admission_event_id)::bigint AS evidence_snapshot_count,
    (SELECT count(*) FROM duplicate_admissions)::bigint AS duplicate_admission_row_count,
    (SELECT count(*) FROM duplicate_jobs)::bigint AS duplicate_logical_job_row_count,
    (SELECT count(*)
       FROM strategy_5scr_analysis_lifecycles_v2 AS lifecycle
       JOIN post_cutover_lifecycles AS post_cutover
         ON post_cutover.strategy_lifecycle_id = lifecycle.strategy_lifecycle_id
      WHERE lifecycle.state IN ('ANALYSIS_OPEN', 'TRANSITION_PENDING'))::bigint AS active_lifecycle_count,
    (SELECT count(DISTINCT event_link.transport_lifecycle_id)::double precision
       FROM strategy_5scr_lifecycle_event_links_v2 AS event_link
       JOIN post_cutover_lifecycles AS lifecycle
         ON lifecycle.strategy_lifecycle_id = event_link.strategy_lifecycle_id)
      / NULLIF((SELECT count(*)::double precision FROM post_cutover_lifecycles), 0)
      AS legacy_to_v2_lifecycle_ratio,
    (SELECT avg(event_count)::double precision FROM event_depth) AS events_per_v2_lifecycle,
    (SELECT avg(clean_block_count)::double precision FROM event_depth) AS clean_blocks_per_v2_lifecycle,
    (SELECT count(*)
       FROM strategy_5scr_evidence_jobs_v2 AS job
       JOIN post_cutover_admissions AS admission
         ON admission.admission_event_id = job.admission_event_id
       LEFT JOIN strategy_5scr_evidence_snapshots_v2 AS snapshot
         ON snapshot.evidence_job_id = job.evidence_job_id
      WHERE job.status = 'COMPLETED' AND snapshot.snapshot_id IS NULL)::bigint
      AS completed_job_without_snapshot_count,
    (SELECT count(*) FROM strategy_5scr_evidence_snapshots_v2 WHERE NOT all_candles_closed)::bigint
      AS forming_candle_used_count,
    (SELECT count(*) FROM strategy_5scr_evidence_snapshots_v2
      WHERE max_source_candle_close > decision_time)::bigint AS future_candle_used_count,
    (SELECT count(*) FROM unexplained_comparisons)::bigint AS unexplained_comparison_difference_count,
    (SELECT count(*) FROM strategy_5scr_evidence_comparisons_v2
      WHERE reason_codes <> '[]'::jsonb)::bigint AS comparison_difference_with_reason_count,
    (SELECT count(*) FROM strategy_5scr_evidence_snapshots_v2 WHERE valid_for_execution)::bigint
      AS valid_for_execution_true_count,
    (SELECT violation_count FROM authority_violations)::bigint AS execution_authority_true_count,
    (SELECT count(*) FROM strategy_5scr_risk_reservations)::bigint AS risk_reservation_row_count,
    (SELECT count(*) FROM strategy_5scr_final_signal_outbox)::bigint AS final_signal_outbox_row_count,
    (SELECT count(*) FROM execution_commands)::bigint AS execution_command_row_count,
    (SELECT count(*) FROM execution_reports)::bigint AS execution_report_row_count,
    broker_counts.broker_order_count,
    broker_counts.broker_deal_count,
    broker_counts.broker_position_count
FROM broker_counts;
