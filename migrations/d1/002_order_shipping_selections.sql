-- Add per-fulfillment-group shipping method selections (e.g. Printful EXPRESS).
-- Fresh installs get the column from SQLModel create_all.

ALTER TABLE orders ADD COLUMN shipping_selections JSON;
