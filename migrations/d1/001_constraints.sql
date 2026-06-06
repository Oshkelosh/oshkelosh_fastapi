-- D1 / SQLite constraints applied after base table creation
CREATE UNIQUE INDEX IF NOT EXISTS idx_cart_items_cart_product
    ON cart_items (cart_id, product_id);

CREATE UNIQUE INDEX IF NOT EXISTS idx_carts_user_id
    ON carts (user_id)
    WHERE user_id IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS idx_addon_configs_addon_id
    ON addon_configs (addon_id);

CREATE UNIQUE INDEX IF NOT EXISTS idx_products_sku
    ON products (sku)
    WHERE sku IS NOT NULL;
