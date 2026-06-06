-- Migration tracking table (idempotent)
CREATE TABLE IF NOT EXISTS schema_migrations (
    filename TEXT PRIMARY KEY NOT NULL,
    applied_at TEXT NOT NULL DEFAULT (datetime('now'))
);
