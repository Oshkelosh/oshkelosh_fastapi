-- Add default billing address on customer accounts (existing DBs).
-- Fresh installs get the column from SQLModel create_all.

ALTER TABLE users ADD COLUMN default_billing_address JSON;
