-- Repair migration: re-apply columns and indexes that a comment-stripping bug in
-- the migration runner skipped while still recording 001-003 as applied.
-- Idempotent: duplicate ADD COLUMN is tolerated by the runner (SQLite and D1),
-- and the index uses IF NOT EXISTS. Fresh installs already have these from
-- SQLModel create_all, so the ALTERs no-op there.

ALTER TABLE users ADD COLUMN default_billing_address JSON;

ALTER TABLE orders ADD COLUMN shipping_selections JSON;

ALTER TABLE site_settings ADD COLUMN shop_currency VARCHAR(3) NOT NULL DEFAULT 'USD';

CREATE UNIQUE INDEX IF NOT EXISTS idx_cart_items_cart_variant
    ON cart_items (cart_id, variant_id);
