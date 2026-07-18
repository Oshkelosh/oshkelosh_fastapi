-- Add configurable shop currency to site settings (existing DBs).
-- Fresh installs get the column from SQLModel create_all.

ALTER TABLE site_settings ADD COLUMN shop_currency VARCHAR(3) NOT NULL DEFAULT 'USD';
