-- Persist per-supplier fulfillment results on orders (existing DBs).
-- Fresh installs get the column from SQLModel create_all.

ALTER TABLE orders ADD COLUMN supplier_orders JSON;
