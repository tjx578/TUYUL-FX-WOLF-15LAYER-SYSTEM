-- =============================================================================
-- Migration: economic_events table
-- File:      migrations/economic_events.sql
-- Purpose:   Persistent storage for canonical economic calendar events.
--
-- Notes:
--   - canonical_id is the provider-agnostic stable identifier.
--   - A partial unique index on canonical_id covers only high/medium
--     confidence events to allow low-confidence duplicates from scraping.
--   - affected_pairs stored as JSONB for efficient membership queries.
--   - Redis is the primary cache; this table is best-effort write-behind.
-- =============================================================================

DROP TABLE IF EXISTS economic_events;
CREATE TABLE economic_events (
    event_id            BIGSERIAL PRIMARY KEY,
    canonical_id        TEXT NOT NULL,
    date                DATE NOT NULL,
    datetime_utc        TIMESTAMPTZ,
    currency            VARCHAR(3),
    event_name          TEXT NOT NULL,
    event_level         VARCHAR(50),
    forecast            DECIMAL(20, 8),
    previous            DECIMAL(20, 8),
    actual              DECIMAL(20, 8),
    source              VARCHAR(100) NOT NULL,
    source_confidence   VARCHAR(20) NOT NULL,
    impact              VARCHAR(20) NOT NULL
                            CHECK (impact IN ('HIGH', 'MEDIUM', 'LOW', 'HOLIDAY', 'UNKNOWN')),

    -- Metadata
    event_url           TEXT,
    status              TEXT NOT NULL DEFAULT 'SCHEDULED'
                            CHECK (status IN ('SCHEDULED', 'RELEASED', 'REVISED', 'CANCELLED')),
    affected_pairs      JSONB NOT NULL DEFAULT '[]'::jsonb,
    fetched_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Audit
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Partial unique index: one canonical record per high/medium-confidence event.
-- Low-confidence (HTML scrape) events are not deduplicated by this index.
-- Note: canonical_id is intentionally NOT marked UNIQUE at table level so that
-- low-confidence duplicates are permitted.
DROP INDEX IF EXISTS uidx_economic_events_canonical_hm;
CREATE UNIQUE INDEX uidx_economic_events_canonical_hm
    ON economic_events (canonical_id)
    WHERE source_confidence = 'high' OR source_confidence = 'medium';

-- Supporting indexes for common query patterns.
-- Date lookup (most common access pattern)
DROP INDEX IF EXISTS idx_economic_events_date;
CREATE INDEX idx_economic_events_date
    ON economic_events (date DESC);

-- Currency filter
DROP INDEX IF EXISTS idx_economic_events_currency;
CREATE INDEX idx_economic_events_currency
    ON economic_events (currency);

-- Impact filter
DROP INDEX IF EXISTS idx_economic_events_impact;
CREATE INDEX idx_economic_events_impact
    ON economic_events (impact);

-- Source label
DROP INDEX IF EXISTS idx_economic_events_source;
CREATE INDEX idx_economic_events_source
    ON economic_events (source);

-- Status filter
DROP INDEX IF EXISTS idx_economic_events_status;
CREATE INDEX idx_economic_events_status
    ON economic_events (status);

-- Time-range queries (datetime_utc can be NULL for timeless events)
DROP INDEX IF EXISTS idx_economic_events_datetime_utc;
CREATE INDEX idx_economic_events_datetime_utc
    ON economic_events (datetime_utc)
    WHERE datetime_utc IS NOT NULL;

-- Composite: date + impact (dashboard calendar filter)
DROP INDEX IF EXISTS idx_economic_events_date_impact;
CREATE INDEX idx_economic_events_date_impact
    ON economic_events (date DESC, impact);

-- JSONB array membership: affected_pairs @> '["EURUSD"]'
DROP INDEX IF EXISTS idx_economic_events_affected_pairs;
CREATE INDEX idx_economic_events_affected_pairs
    ON economic_events USING GIN (affected_pairs);

-- Validation trigger: ensure affected_pairs is a valid JSONB array
DROP FUNCTION IF EXISTS _validate_economic_events();
CREATE FUNCTION _validate_economic_events()
RETURNS TRIGGER AS $$
BEGIN
    IF jsonb_typeof(NEW.affected_pairs) <> 'array' THEN
        RAISE EXCEPTION 'affected_pairs must be a JSONB array';
    END IF;
    NEW.updated_at := NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_validate_economic_events ON economic_events;
CREATE TRIGGER trg_validate_economic_events
    BEFORE INSERT OR UPDATE ON economic_events
    FOR EACH ROW EXECUTE FUNCTION _validate_economic_events();
