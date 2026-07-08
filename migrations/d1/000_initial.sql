-- Initial schema supplements (applied after SQLModel table creation)

-- Migration tracking
CREATE TABLE IF NOT EXISTS schema_migrations (
    filename TEXT PRIMARY KEY NOT NULL,
    applied_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Manual supplier definitions for non-API fulfillment
CREATE TABLE IF NOT EXISTS manual_suppliers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    slug TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    contact_email TEXT,
    contact_phone TEXT,
    notes TEXT,
    is_active INTEGER NOT NULL DEFAULT 1
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_manual_suppliers_slug
    ON manual_suppliers (slug);

-- Indexes and constraints
CREATE UNIQUE INDEX IF NOT EXISTS idx_cart_items_cart_variant
    ON cart_items (cart_id, variant_id);

CREATE INDEX IF NOT EXISTS idx_product_variants_supplier_external_key
    ON product_variants (supplier_external_key)
    WHERE supplier_external_key IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_products_supplier_external_product_key
    ON products (supplier_external_product_key)
    WHERE supplier_external_product_key IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS idx_product_variants_sku
    ON product_variants (sku)
    WHERE sku IS NOT NULL;

DROP INDEX IF EXISTS idx_cart_items_cart_product;

CREATE UNIQUE INDEX IF NOT EXISTS idx_carts_user_id
    ON carts (user_id)
    WHERE user_id IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS idx_addon_configs_addon_id
    ON addon_configs (addon_id);

CREATE UNIQUE INDEX IF NOT EXISTS idx_products_sku
    ON products (sku)
    WHERE sku IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_orders_payment_id
    ON orders (payment_id)
    WHERE payment_id IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS idx_order_idempotency_user_key
    ON order_idempotency_keys (user_id, key_hash);

CREATE UNIQUE INDEX IF NOT EXISTS idx_users_single_admin
    ON users (is_admin)
    WHERE is_admin = 1;

-- SEO: product slugs (columns live in SQLModel models, no production DB to migrate)
UPDATE products SET slug = 'product-' || id WHERE slug IS NULL OR slug = '';

CREATE UNIQUE INDEX IF NOT EXISTS idx_products_slug ON products (slug);

-- notification_templates and user push fields (push_provider, push_token) are
-- created by SQLModel from models/notification_template.py and models/user.py

