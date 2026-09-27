-- Notification templates, push columns, and abandoned-cart fields for existing DBs.
-- Fresh installs already get these from SQLModel create_all; duplicate ADD COLUMN
-- is tolerated by the runner (SQLite and D1). D1 HTTP create_all does not emit
-- the unique (event_key, channel) constraint.

CREATE TABLE IF NOT EXISTS notification_templates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_key VARCHAR(64) NOT NULL,
    channel VARCHAR(16) NOT NULL,
    subject VARCHAR(512) NOT NULL,
    body TEXT NOT NULL,
    is_enabled BOOLEAN NOT NULL DEFAULT 1
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_notification_templates_event_channel
    ON notification_templates (event_key, channel);

CREATE INDEX IF NOT EXISTS ix_notification_templates_event_key
    ON notification_templates (event_key);

CREATE INDEX IF NOT EXISTS ix_notification_templates_channel
    ON notification_templates (channel);

ALTER TABLE users ADD COLUMN push_provider VARCHAR(32);
ALTER TABLE users ADD COLUMN push_token VARCHAR(512);

ALTER TABLE carts ADD COLUMN abandoned_reminded_at DATETIME;
ALTER TABLE carts ADD COLUMN abandoned_reminder_count INTEGER NOT NULL DEFAULT 0;

ALTER TABLE site_settings ADD COLUMN abandoned_cart_enabled BOOLEAN NOT NULL DEFAULT 0;
ALTER TABLE site_settings ADD COLUMN abandoned_cart_delay_hours INTEGER NOT NULL DEFAULT 24;
ALTER TABLE site_settings ADD COLUMN abandoned_cart_max_reminders INTEGER NOT NULL DEFAULT 1;
