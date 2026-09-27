-- Outbound HMAC webhook receiver (existing DBs).
-- Fresh installs get the table from SQLModel create_all.

CREATE TABLE IF NOT EXISTS outbound_webhook_endpoints (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    enabled INTEGER NOT NULL DEFAULT 0,
    url VARCHAR(2048),
    secret VARCHAR(128),
    events JSON NOT NULL DEFAULT '[]',
    last_status INTEGER,
    last_error TEXT,
    last_sent_at TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
