-- Indexes for the two hot order queries: per-user listing and
-- status/staleness scans (cleanup jobs, admin filters).
-- Fresh installs get these from SQLModel create_all (__table_args__).

CREATE INDEX IF NOT EXISTS idx_orders_user_id ON orders (user_id);

CREATE INDEX IF NOT EXISTS idx_orders_status_created_at ON orders (status, created_at);
