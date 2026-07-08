# Manual suppliers (`manual`)

Fulfill orders through admin-defined suppliers without an external API. On paid orders, structured fulfillment instructions are written to `order.notes`.

## Overview

| | |
|---|---|
| Addon ID | `manual` |
| Category | supplier |
| Version | 1.0.0 |
| Category guide | [../README.md](../README.md) |
| Catalog sync | No |

Multiple suppliers can be enabled at the same time. Manual fulfillment runs when an order transitions to **paid**.

## Enable and configure

1. Open **Admin → Suppliers → Manual** at `/admin/suppliers/manual`
2. Create one or more manual supplier definitions (name, slug, contact)
3. Enable the addon via **Settings** on the same page (`is_active`)

You can manage supplier definitions even when the addon is disabled; enable it to activate fulfillment on paid orders.

## Configuration schema

| Field | Type | Description |
|-------|------|-------------|
| `is_active` | bool | Whether manual fulfillment runs on paid orders |

Supplier definitions (name, slug, contact, active flag) live in the **`manual_suppliers`** database table, not in `addon_configs`.

## Routes

### Admin

| Method | Path | Description |
|--------|------|-------------|
| GET | `/admin/suppliers/manual` | List manual suppliers |
| GET | `/admin/suppliers/manual/new` | Add form |
| POST | `/admin/suppliers/manual/create` | Create supplier |
| GET | `/admin/suppliers/manual/{slug}/edit` | Edit form |
| POST | `/admin/suppliers/manual/{slug}/save` | Update supplier |
| POST | `/admin/suppliers/manual/{slug}/delete` | Delete supplier |
| POST | `/admin/suppliers/manual/settings` | Enable/disable addon |

### Public API

None — fulfillment is triggered by core when order status becomes `paid`.

## Core integration

- **Variant supplier fields:** fulfillment reads `supplier_addon_id`, `supplier_variant_id` (manual slug), and optional `supplier_product_id` from each **ProductVariant** row
- **Fulfillment key:** `manual:{slug}`
- **Paid orders:** `create_order()` appends structured fulfillment instructions to `order.notes` (no external HTTP call)
- **Admin product form:** dropdown options from active rows in `manual_suppliers`; supplier choice is stored on the default variant at create time

## Variant supplier fields

Set on each sellable variant in **Admin → Products** (variants table) or on `product_variants` rows:

| Field | Required | Description |
|-------|----------|-------------|
| `supplier_addon_id` | yes | Must be `"manual"` |
| `supplier_variant_id` | yes | Slug from `manual_suppliers` (lowercase letters, digits, underscores) |
| `supplier_product_id` | no | Your SKU or internal reference |

Admin dropdown values use the format `manual:{slug}`; the slug is persisted on the variant as `supplier_variant_id`.

## Operator workflow

1. Create manual suppliers at `/admin/suppliers/manual`
2. Assign a manual supplier on each variant that should be fulfilled externally
3. When a customer pays, line items grouped by `manual:{slug}` produce fulfillment notes on the order
4. Fulfill orders manually using the notes (pick/pack/ship outside Oshkelosh)

## Package layout

```
manual/
├── README.md
├── addon.py
├── routes.py
└── templates/
```

## See also

- [Supplier addon development](../README.md)
- [Oshkelosh addon guide](../../README.md)
