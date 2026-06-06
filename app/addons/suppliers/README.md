# Supplier addon development

Supplier addons connect to print-on-demand or fulfillment providers (Printful, etc.) for catalog sync and order placement.

## Policy

- **Multiple suppliers** can be enabled.
- Fulfillment runs when an order transitions to **`paid`**.
- Only products **tagged** for a supplier are sent to that provider.

## SupplierAddon methods

| Method | Purpose |
|--------|---------|
| `list_products(**kwargs)` | Catalog from provider |
| `get_product(product_id)` | Single product |
| `create_order(product_ids, shipping_address)` | Place fulfillment order |
| `get_order_status(order_id)` | Track shipment |
| `sync_inventory()` | Sync stock levels |

## Product linkage (required for auto-fulfillment)

Add tags on the `Product` model's `tags` JSON array:

```json
{
  "supplier_addon_id": "printful",
  "supplier_product_id": "12345"
}
```

Core [`app/services/fulfillment.py`](../../services/fulfillment.py) groups line items by `supplier_addon_id` and calls `create_order()`.

Orders without tagged products skip supplier fulfillment (local inventory only).

## Package layout

```
app/addons/suppliers/<provider>/
├── addon.py
├── routes.py      # e.g. GET .../products, admin config
└── templates/
```

## Route mounting

| Type | URL pattern | Example |
|------|-------------|---------|
| API | `/api/v1/suppliers/{addon_id}/...` | `GET /api/v1/suppliers/printful/products` |
| Admin | `/admin/suppliers/{addon_id}/...` | `GET /admin/suppliers/printful` |

OpenAPI tag: **`addons-suppliers`**

## Configuration

API keys are configured in the admin panel at `/admin/suppliers/{addon_id}` (stored in `addon_configs`), not in `.env`.

## Shipping address

`create_order()` receives `shipping_address` from `order.shipping_address` (JSON). Expected keys:

- `first_name`, `last_name`, `email`
- `line1`, `city`, `state`, `zip`, `country`

Ensure checkout collects these fields if you rely on supplier fulfillment.

## Reference addon

[`printful/`](printful/) — catalog list, order creation, admin config.

## OpenAPI

Tag `addons-suppliers` in [docs/api/OPENAPI.md](../../../docs/api/OPENAPI.md).
