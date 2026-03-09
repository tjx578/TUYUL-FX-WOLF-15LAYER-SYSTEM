-- Migration: create economic_events table
CREATE TABLE IF NOT EXISTS economic_events (
    event_id          TEXT         PRIMARY KEY,
    canonical_id      TEXT         NOT NULL,
    source            TEXT         NOT NULL,
    source_confidence TEXT         NOT NULL DEFAULT 'high'
                                   CHECK (source_confidence IN ('high','medium','low')),
    title             TEXT         NOT NULL,
    currency          CHAR(8)      NOT NULL,
    country           CHAR(8),
    impact            TEXT         NOT NULL CHECK (impact IN ('HIGH','MEDIUM','LOW','UNKNOWN')),
    impact_score      SMALLINT     NOT NULL DEFAULT 0 CHECK (impact_score BETWEEN 0 AND 3),
    event_time_utc    TIMESTAMPTZ,
    timezone_source   TEXT,
    is_timeless       BOOLEAN      NOT NULL DEFAULT FALSE,
    actual            TEXT,
    forecast          TEXT,
    previous          TEXT,
    better_direction  TEXT,
    status            TEXT         NOT NULL DEFAULT 'unknown',
    event_url         TEXT,
    affected_pairs    JSONB        NOT NULL DEFAULT '[]'::jsonb,
    raw_json          JSONB        NOT NULL DEFAULT '{}'::jsonb,
    fetched_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_economic_events_date
    ON economic_events (DATE(event_time_utc));

CREATE INDEX IF NOT EXISTS idx_economic_events_currency
    ON economic_events (currency);

CREATE INDEX IF NOT EXISTS idx_economic_events_impact
    ON economic_events (impact_score DESC);

CREATE INDEX IF NOT EXISTS idx_economic_events_source
    ON economic_events (source);

CREATE INDEX IF NOT EXISTS idx_economic_events_status
    ON economic_events (status);

CREATE INDEX IF NOT EXISTS idx_economic_events_date_impact
    ON economic_events (DATE(event_time_utc), impact_score DESC);

CREATE UNIQUE INDEX IF NOT EXISTS idx_economic_events_canonical_id
    ON economic_events (canonical_id)
    WHERE source_confidence IN ('high', 'medium');

COMMENT ON TABLE economic_events IS
    'Normalized economic calendar events. canonical_id = provider-agnostic dedup key.';
COMMENT ON COLUMN economic_events.is_timeless IS
    'True = All Day / Tentative. BlockerEngine must NOT apply lock windows to these.';
COMMENT ON COLUMN economic_events.source_confidence IS
    'high=structured feed, low=HTML scrape (treat with suspicion).';
    