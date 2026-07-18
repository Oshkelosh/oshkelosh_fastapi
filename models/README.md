# models — SQLModel tables

One table per file; all inherit `ModelBase` (`id`, `created_at`, `updated_at`).
Import via `models` package (`from models.order import Order`). New models must
be imported in `models/__init__.py` so `SQLModel.metadata.create_all` sees them.

| Model | Table | Notes |
|-------|-------|-------|
| `User` | `users` | Auth, default shipping/billing addresses, single-admin partial index |
| `Category` / `Product` / `ProductVariant` / `ProductImage` | catalog | Variants hold price/inventory/supplier linkage; products hold content/tags |
| `Cart` / `CartItem` | cart | One cart per user; `(cart_id, variant_id)` unique |
| `Order` / `OrderItem` | orders | Integer-cent money; frozen line prices; `shipping_selections` + `supplier_orders` JSON |
| `OrderIdempotencyKey` | order dedupe | Unique `(user_id, key_hash)` |
| `ProcessedWebhookEvent` | webhook replay guard | Unique `event_id` per provider event |
| `SiteSettings` | singleton | Shop currency, tax/shipping defaults, branding |
| `AddonConfig` | addon state | Per-addon config JSON + enabled flag |
| `ManualSupplier` | manual fulfillment | Queried via `app/services/manual_suppliers.py` |
| `NotificationTemplate`, `AuditLog`, `BackgroundJob` | supporting | — |

Schema changes for existing databases go through `migrations/d1/` (see
[docs/DATABASE.md](../docs/DATABASE.md)); fresh installs get tables from
SQLModel bootstrap.
