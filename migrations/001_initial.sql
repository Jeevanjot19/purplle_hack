CREATE TABLE IF NOT EXISTS events (
    event_id        UUID            PRIMARY KEY,
    store_id        VARCHAR(50)     NOT NULL,
    camera_id       VARCHAR(50)     NOT NULL,
    visitor_id      VARCHAR(50)     NOT NULL,
    event_type      VARCHAR(30)     NOT NULL,
    timestamp       TIMESTAMPTZ     NOT NULL,
    zone_id         VARCHAR(50),
    dwell_ms        INTEGER         NOT NULL DEFAULT 0,
    is_staff        BOOLEAN         NOT NULL DEFAULT FALSE,
    confidence      FLOAT           NOT NULL,
    queue_depth     INTEGER,
    sku_zone        VARCHAR(50),
    session_seq     INTEGER         NOT NULL DEFAULT 0,
    ingested_at     TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_events_store_ts
    ON events(store_id, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_events_visitor_ts
    ON events(visitor_id, timestamp ASC);
CREATE INDEX IF NOT EXISTS idx_events_store_type
    ON events(store_id, event_type, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_events_store_zone
    ON events(store_id, zone_id, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_events_store_staff
    ON events(store_id, is_staff, event_type);

CREATE TABLE IF NOT EXISTS sessions (
    visitor_id          VARCHAR(50)     PRIMARY KEY,
    store_id            VARCHAR(50)     NOT NULL,
    entry_time          TIMESTAMPTZ,
    exit_time           TIMESTAMPTZ,
    zones_visited       JSONB           NOT NULL DEFAULT '[]',
    reached_billing     BOOLEAN         NOT NULL DEFAULT FALSE,
    converted           BOOLEAN         NOT NULL DEFAULT FALSE,
    basket_value        NUMERIC(10,2),
    is_staff            BOOLEAN         NOT NULL DEFAULT FALSE,
    reentry_count       INTEGER         NOT NULL DEFAULT 0,
    last_updated        TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_sessions_store_entry
    ON sessions(store_id, entry_time DESC);
CREATE INDEX IF NOT EXISTS idx_sessions_store_converted
    ON sessions(store_id, is_staff, converted);

CREATE TABLE IF NOT EXISTS pos_transactions (
    transaction_id  VARCHAR(50)     PRIMARY KEY,
    store_id        VARCHAR(50)     NOT NULL,
    timestamp       TIMESTAMPTZ     NOT NULL,
    basket_value    NUMERIC(10,2)   NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_pos_store_ts
    ON pos_transactions(store_id, timestamp DESC);

CREATE TABLE IF NOT EXISTS anomaly_log (
    id              SERIAL          PRIMARY KEY,
    store_id        VARCHAR(50)     NOT NULL,
    anomaly_type    VARCHAR(50)     NOT NULL,
    severity        VARCHAR(10)     NOT NULL
                    CHECK (severity IN ('INFO','WARN','CRITICAL')),
    detected_at     TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    resolved_at     TIMESTAMPTZ,
    metadata        JSONB           NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_anomaly_store_active
    ON anomaly_log(store_id, detected_at DESC)
    WHERE resolved_at IS NULL;
