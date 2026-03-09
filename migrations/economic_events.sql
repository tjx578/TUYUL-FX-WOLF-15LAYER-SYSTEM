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

-- ...existing code...

    -- Metadata
    event_url           TEXT,
    status              TEXT        NOT NULL DEFAULT 'SCHEDULED'
                                    CHECK (status = 'SCHEDULED' OR status = 'RELEASED' OR status = 'REVISED' OR status = 'CANCELLED'),
    affected_pairs      JSONB       NOT NULL DEFAULT '[]'::jsonb,
    fetched_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Audit
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    PRIMARY KEY (event_id),
    CHECK (impact IN ('HIGH', 'MEDIUM', 'LOW', 'HOLIDAY', 'UNKNOWN')),
    CHECK (jsonb_typeof(affected_pairs) = 'array')
);

-- ...existing code...CREATE TABLE economic_events (
    -- Row identity
    event_id            TEXT        NOT NULL,
    canonical_id        TEXT        NOT NULL,

    -- Source provenance
    source              TEXT        NOT NULL,
    source_confidence   TEXT        NOT NULL CHECK (source_confidence IN ('high', 'medium', 'low')),

    -- Content
    title               TEXT        NOT NULL,
    currency            TEXT        NOT NULL,
    country             TEXT,

    -- Impact
    impact              TEXT        NOT NULL CHECK (impact IN ('HIGH', 'MEDIUM', 'LOW', 'HOLIDAY', 'UNKNOWN')),
    impact_score        SMALLINT    NOT NULL DEFAULT 0,

    -- Temporal
    date                DATE        NOT NULL,
    time                TEXT        NOT NULL DEFAULT '',
    datetime_utc        TIMESTAMPTZ,
    timezone_source     TEXT        NOT NULL DEFAULT 'America/New_York',
    is_timeless         BOOLEAN     NOT NULL DEFAULT FALSE,

    -- Economic values
    actual              TEXT,
    forecast            TEXT,
    previous            TEXT,
    better_direction    TEXT,

    -- Metadata
    event_url           TEXT,
    status              TEXT        NOT NULL DEFAULT 'SCHEDULED'
                                    CHECK (status IN ('SCHEDULED', 'RELEASED', 'REVISED', 'CANCELLED')),
    affected_pairs      JSONB       NOT NULL DEFAULT '[]',
    fetched_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Audit
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    PRIMARY KEY (event_id)
);

-- ---------------------------------------------------------------------------
-- Partial unique index: one canonical record per high/medium-confidence event.
-- Low-confidence (HTML scrape) events are not deduplicated by this index.
-- ---------------------------------------------------------------------------
CREATE UNIQUE INDEX IF NOT EXISTS uidx_economic_events_canonical_hm
    ON economic_events (canonical_id)
    WHERE source_confidence IN ('high', 'medium');

-- ---------------------------------------------------------------------------
-- Supporting indexes for common query patterns.
-- ---------------------------------------------------------------------------

-- Date lookup (most common access pattern)
CREATE INDEX IF NOT EXISTS idx_economic_events_date
    ON economic_events (date DESC);

-- Currency filter
CREATE INDEX IF NOT EXISTS idx_economic_events_currency
    ON economic_events (currency);

-- Impact filter
CREATE INDEX IF NOT EXISTS idx_economic_events_impact
    ON economic_events (impact);

-- Source label
CREATE INDEX IF NOT EXISTS idx_economic_events_source
    ON economic_events (source);

-- Status filter
CREATE INDEX IF NOT EXISTS idx_economic_events_status
    ON economic_events (status);

-- Time-range queries (datetime_utc can be NULL for timeless events)
CREATE INDEX IF NOT EXISTS idx_economic_events_datetime_utc
    ON economic_events (datetime_utc)
    WHERE datetime_utc IS NOT NULL;

-- Composite: date + impact (dashboard calendar filter)
CREATE INDEX IF NOT EXISTS idx_economic_events_date_impact
    ON economic_events (date DESC, impact);

-- JSONB array membership: affected_pairs @> '["EURUSD"]'
CREATE INDEX IF NOT EXISTS idx_economic_events_affected_pairs
    ON economic_events USING GIN (affected_pairs);

-- ---------------------------------------------------------------------------
-- Auto-update updated_at trigger
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION _update_economic_events_updated_at()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_economic_events_updated_at ON economic_events;
CREATE TRIGGER trg_economic_events_updated_at
    BEFORE UPDATE ON economic_events
    FOR EACH ROW EXECUTE FUNCTION _update_economic_events_updated_at();
