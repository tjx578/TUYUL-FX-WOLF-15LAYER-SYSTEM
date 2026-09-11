-- WOLF15_5SCR_RESTART_COMPARE_V1
-- Reference query for operators using psql.
-- Parameters $1 and $2 are the capture objects from before/after JSON output.
-- The Python auditor performs the same comparison without requiring a DB.

WITH captures AS (
    SELECT $1::jsonb AS before_capture, $2::jsonb AS after_capture
),
fields(field_name) AS (
    VALUES
        ('strategy_lifecycle_id'),
        ('admission_event_id'),
        ('pressure_event_id'),
        ('raw_lineage_hash'),
        ('evidence_job_id'),
        ('decision_time'),
        ('material_state_hash'),
        ('context_hash'),
        ('evidence_hash')
)
SELECT field_name,
       before_capture ->> field_name AS before_value,
       after_capture ->> field_name AS after_value,
       (before_capture ->> field_name) IS DISTINCT FROM (after_capture ->> field_name) AS drifted
FROM captures
CROSS JOIN fields
ORDER BY field_name;
