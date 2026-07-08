# Supplier addon development

Supplier addons connect to print-on-demand or fulfillment providers for catalog sync and order placement. Each installed package includes its own README with provider-specific config, variant field mapping, and setup steps.

## Product and variant model

Oshkelosh separates **listing** from **sellable units**:

| Concept | Table / field | Role |
|---------|---------------|------|
| **Product** | `products` | One design or listing (name, slug, description, SEO, category) |
| **Variant** | `product_variants` | Purchasable SKU — price, stock, supplier IDs, picker attributes |
| **Creator options** | `products.options` (JSON) | Display-only specs (material, care, dimensions) — **not** purchasable |
| **Variant attributes** | `product_variants.attributes` (JSON) | Picker hints (Size, Color) shown on the storefront |
| **Listing cache** | `products.price_cents`, `inventory_quantity`, `has_variants` | Denormalized from active variants for list views |

Cart and order line items reference **`variant_id`**. Fulfillment, shipping quotes, and supplier catalog sync all resolve supplier linkage from **variant rows**, not from `products.tags`.

### Supplier fields on variants

Each `ProductVariant` can carry:

| Field | Purpose |
|-------|---------|
| `supplier_addon_id` | Addon id (`printful`, `manual`, …) |
| `supplier_product_id` | Provider parent / product identifier |
| `supplier_variant_id` | Provider variant identifier (when required) |
| `supplier_external_key` | Stable dedup key for catalog sync (`printful:variant:123`, …) |

Products synced from a supplier also set `products.supplier_external_product_key` (parent design key, e.g. `printful:product:456`).

**Manual products:** Admin create flow stores supplier choice on the **default variant** created by `create_default_variant()`. For manual suppliers, `supplier_variant_id` holds the `manual_suppliers` slug.

**Legacy `products.tags`:** No longer used for fulfillment. Addon `parse_assignment()` / `build_tag_from_form()` hooks remain for backward compatibility and admin form helpers.

## Data model

Supplier data lives in three intentional layers:

| Layer | API suppliers | Manual suppliers |
|-------|---------------|------------------|
| Integration code | Addon package under `app/addons/suppliers/<id>/` | Built-in `manual` addon |
| Credentials / definitions | `addon_configs` (JSON + `is_enabled`) | `manual_suppliers` table (slug, name, contact) |
| Product linkage | `product_variants.supplier_*` fields | Same variant fields (`supplier_addon_id=manual`, slug in `supplier_variant_id`) |

The asymmetry is deliberate: API integrations need code and secrets; manual partners are merchant-defined records editable in admin without deploys.

**Fulfillment keys** group paid-order line items before calling `create_order()`. Each addon implements `fulfillment_key()` — typically the addon id, or `manual:{slug}` for manual suppliers. Core [`app/services/product_variants.py`](../../services/product_variants.py) builds `SupplierAssignment` from variant rows; fulfillment routing lives in [`app/services/fulfillment.py`](../../services/fulfillment.py).

**Admin product form:** supplier dropdown and per-variant supplier fields appear on **Admin → Products** (variants table on edit). Only **enabled** API supplier addons appear in dropdowns. Manual choices come from **active** rows in `manual_suppliers` when the `manual` package is registered.

## Policy

- **Multiple suppliers** can be enabled at the same time (unlike payment/frontend).
- Fulfillment runs when an order transitions to **`paid`**.
- Only line items whose **variant** has a supplier assignment are sent to a provider.
- A single order may fan out to **several suppliers**; each group is fulfilled independently.

## SupplierAddon methods

| Method | Purpose |
|--------|---------|
| `supports_catalog_sync()` | Whether remote catalog import is available |
| `fetch_catalog_for_import()` | Fetch + normalize remote catalog to `SupplierCatalogProduct[]` |
| `parse_assignment(tag)` | Parse a legacy product tag into a `SupplierAssignment` |
| `build_tag_from_form(...)` | Build a supplier tag from admin form values (legacy / form helpers) |
| `validate_admin_form(...)` | Validate admin variant supplier fields |
| `external_key_from_assignment(...)` | Stable catalog sync key for manually assigned variants |
| `fulfillment_key(assignment)` | Grouping key for paid-order line items |
| `admin_form_hints()` | Metadata for admin variant form (field labels, help text) |
| `list_admin_options(session)` | Dropdown options for admin product form |
| `export_config_updates()` | Persist runtime config after API calls (e.g. OAuth tokens) |
| `list_products(**kwargs)` | Raw catalog passthrough for API routes |
| `get_product(product_id)` | Single product |
| `create_order(items, shipping_address, ...)` | Place fulfillment order |
| `supports_shipping_quotes()` | Whether this addon can quote shipping for checkout |
| `quote_shipping(items, shipping_address)` | Return shipping cents for a fulfillment group, or `None` to defer to Site Settings |
| `get_order_status(order_id)` | Track shipment |
| `sync_inventory()` | Sync stock levels |

`create_order` receives line items as `{supplier_product_id, supplier_variant_id?, quantity, product_name?}` plus optional `external_id` (Oshkelosh order id) and `supplier_ref` (manual supplier slug).

## Fulfillment flow

On `paid`, [`fulfillment.py`](../../services/fulfillment.py):

1. Loads each order line's `ProductVariant`.
2. Calls `supplier_assignment_from_variant()` in [`product_variants.py`](../../services/product_variants.py).
3. Groups items by `fulfillment_key()`.
4. Calls `create_order()` per group.

Lines without a variant supplier assignment skip supplier fulfillment (digital / self-fulfilled products).

## Shipping quotes at checkout

Core [`app/services/checkout_pricing.py`](../../services/checkout_pricing.py) groups cart line items by the same `fulfillment_key()` used for fulfillment. For each group:

1. If the supplier addon returns `supports_shipping_quotes() == True`, core calls `quote_shipping(items, shipping_address)`.
2. If the addon returns a cent amount, that value is added to the order shipping total.
3. If the addon returns `None`, or the variant has no supplier assignment, core applies **Site Settings** shipping rules (flat, free, threshold, or zones) to the unquoted subtotal.

Multi-supplier carts sum per-group supplier quotes plus one Site Settings application for unquoted lines. Implement `quote_shipping()` only when the provider API supports rate lookup — do not add carrier APIs (EasyPost/Shippo) as separate tool addons.

## Catalog sync

API supplier addons implement **`fetch_catalog_for_import()`**, returning normalized [`SupplierCatalogProduct`](../../../schemas/supplier.py) rows (each with child [`SupplierCatalogVariant`](../../../schemas/supplier.py) entries). Core [`supplier_catalog_sync.py`](../../services/supplier_catalog_sync.py) upserts:

- **One `Product`** per catalog product (design), keyed by `supplier_external_product_key`
- **One `ProductVariant`** per catalog variant, keyed by `supplier_external_key`
- Per-variant images, prices, inventory, and supplier IDs

[`catalog_utils.py`](catalog_utils.py) provides shared normalization helpers (price conversion, attribute extraction, flat-item → grouped product conversion).

**Admin UI:** Each supplier config page includes a **Catalog sync** card.

**Admin API:** `POST /api/v1/admin/suppliers/{addon_id}/sync` with body:

```json
{
  "import_status": "draft",
  "archive_missing": false
}
```

Supplier packages are typically installed via admin ZIP/URL or kept locally. Only `manual` is tracked in-repo.

## Installed supplier addons

Each package includes a `README.md` with config, variant field mapping, catalog sync prerequisites, and provider setup:

| Addon ID | README |
|----------|--------|
| `manual` | [manual/README.md](manual/README.md) |
| `printful` | [printful/README.md](printful/README.md) (when installed) |
| `printify` | [printify/README.md](printify/README.md) (when installed) |
| `gelato` | [gelato/README.md](gelato/README.md) (when installed) |
| `prodigi` | [prodigi/README.md](prodigi/README.md) (when installed) |
| `gooten` | [gooten/README.md](gooten/README.md) (when installed) |
| `cjdropshipping` | [cjdropshipping/README.md](cjdropshipping/README.md) (when installed) |
| `customcat` | [customcat/README.md](customcat/README.md) (when installed) |
| `spreadconnect` | [spreadconnect/README.md](spreadconnect/README.md) (when installed) |
| `podbase` | [podbase/README.md](podbase/README.md) (when installed) |

## Package layout

```
app/addons/suppliers/<provider>/
├── README.md
├── addon.py
├── catalog.py     # provider-specific normalization (optional)
├── client.py      # HTTP client (optional)
├── routes.py
└── templates/
```

Shared: [`shared_routes.py`](shared_routes.py), [`catalog_utils.py`](catalog_utils.py).

## Route mounting

| Type | URL pattern | Example |
|------|-------------|---------|
| API | `/api/v1/suppliers/{addon_id}/...` | `GET /api/v1/suppliers/{addon_id}/products` |
| Admin | `/admin/suppliers/{addon_id}/...` | `GET /admin/suppliers/{addon_id}` |

OpenAPI tag: **`addons-suppliers`**

## Configuration

Credentials are configured in the admin panel at `/admin/suppliers/{addon_id}` (stored in `addon_configs`), not in `.env`.

## Shipping address

`create_order()` receives `shipping_address` from `order.shipping_address` (JSON). Expected keys:

- `first_name`, `last_name`, `email`
- `line1`, `city`, `state`, `zip`, `country`

Ensure checkout collects these fields if you rely on supplier fulfillment.

## OpenAPI

Tag `addons-suppliers` in [docs/api/OPENAPI.md](../../../docs/api/OPENAPI.md).
