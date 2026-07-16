# Services layer

Core business logic lives in `app/services/`. Routers and admin routes stay thin; they call these modules for orchestration, validation, and persistence.

**Orchestration seams** resolve enabled addons and call addon ABC methods — extend addons instead of adding provider branches here. **Utilities** implement core-only behavior (persistence helpers, discovery glue, formatting) and do not embed PSP or supplier specifics.

## Module index by domain

### Commerce and orders

| Module | Role | Type |
|--------|------|------|
| [`commerce.py`](commerce.py) | Inventory, cart/order loading, status transitions | Utility |
| [`checkout_pricing.py`](checkout_pricing.py) | Tax and shipping at order creation | Seam |
| [`payment_checkout.py`](payment_checkout.py) | Start checkout via enabled `PaymentAddon` | Seam |
| [`payment_webhooks.py`](payment_webhooks.py) | Idempotent webhook handling | Seam |
| [`payments.py`](payments.py) | `complete_order_payment` side effects | Utility |
| [`fulfillment.py`](fulfillment.py) | Supplier order creation on `paid` | Seam |
| [`order_idempotency.py`](order_idempotency.py) | Order-creation idempotency keys | Utility |
| [`pending_order_cleanup.py`](pending_order_cleanup.py) | Cancel stale pending orders | Utility |

### Addons and suppliers

| Module | Role | Type |
|--------|------|------|
| [`addons.py`](addons.py) | Registry lookup, `persist_addon_config` | Utility |
| [`addon_install.py`](addon_install.py) | ZIP/URL addon install pipeline | Utility |
| [`suppliers.py`](suppliers.py) | Supplier assignment helpers and addon delegation | Seam |
| [`product_variants.py`](product_variants.py) | Variant CRUD, listing cache, supplier lookup, snapshots | Utility |
| [`supplier_catalog_sync.py`](supplier_catalog_sync.py) | Import supplier catalogs into products + variants | Seam |

### Notifications and lifecycle

| Module | Role | Type |
|--------|------|------|
| [`notifications.py`](notifications.py) | Order-status notification fan-out | Seam |
| [`notification_dispatch.py`](notification_dispatch.py) | Route rendered messages to channels | Utility |
| [`notification_events.py`](notification_events.py) | Event keys, channels, placeholders | Utility |
| [`notification_templates.py`](notification_templates.py) | Load and render templates | Utility |
| [`abandoned_cart.py`](abandoned_cart.py) | Stale-cart recovery job | Seam |
| [`lifecycle_events.py`](lifecycle_events.py) | CRM/marketing tool fan-out | Seam |

### Storefront and catalog

| Module | Role | Type |
|--------|------|------|
| [`storefront_resolver.py`](storefront_resolver.py) | Active frontend addon routing | Seam |
| [`product_search.py`](product_search.py) | Core ILIKE + optional search tools | Seam |
| [`product_images.py`](product_images.py) | Upload, import, and resolve images | Utility |
| [`product_slugs.py`](product_slugs.py) | Slug generation and uniqueness | Utility |
| [`product_defaults.py`](product_defaults.py) | Creation defaults and API validation | Utility |
| [`product_variants.py`](product_variants.py) | Variant resolution, listing cache, supplier assignment | Utility |
| [`product_popularity.py`](product_popularity.py) | `units_sold` and ranking | Utility |
| [`tool_discovery.py`](tool_discovery.py) | Storefront scripts, commerce events | Seam |
| [`tax_discovery.py`](tax_discovery.py) | Third-party tax tool resolution | Seam |
| [`sso_discovery.py`](sso_discovery.py) | Public SSO provider metadata | Seam |
| [`push_discovery.py`](push_discovery.py) | Public push subscription config | Seam |
| [`sso_accounts.py`](sso_accounts.py) | OAuth identity linking | Utility |

### Platform

| Module | Role | Type |
|--------|------|------|
| [`site_settings.py`](site_settings.py) | Site-wide settings singleton | Utility |
| [`user_accounts.py`](user_accounts.py) | Verification, password reset, addresses | Utility |
| [`auth_tokens.py`](auth_tokens.py) | JWT encode/decode helpers | Utility |
| [`bootstrap.py`](bootstrap.py) | First-admin creation | Utility |
| [`audit.py`](audit.py) | Admin change audit log | Utility |
| [`background_jobs.py`](background_jobs.py) | DB-backed admin jobs | Utility |
| [`system_health.py`](system_health.py) | Readiness and dashboard health | Utility |
| [`r2.py`](r2.py) | Cloudflare R2 media storage | Utility |

### Pricing (`pricing/`)

| Module | Role | Type |
|--------|------|------|
| [`pricing/protocols.py`](pricing/protocols.py) | Tax/shipping quote result types | Utility |
| [`pricing/shipping.py`](pricing/shipping.py) | Supplier-aware shipping quotes | Seam |
| [`pricing/tax_rules.py`](pricing/tax_rules.py) | Built-in tax/shipping math | Utility |

## How core commerce uses addons

Mirrors [app/addons/README.md](../addons/README.md#how-core-commerce-uses-addons). Patch addons or expose provider routes — avoid provider `if` branches in core services.

| Event | Service | Addon used |
|-------|---------|------------|
| Order creation (tax & shipping) | `checkout_pricing.py` | Site Settings rules; optional `ToolAddon.quote_tax()`; optional `SupplierAddon.quote_shipping()` |
| Checkout | `POST /api/v1/orders/{id}/checkout` → `payment_checkout.py` | First enabled `PaymentAddon` |
| Payment webhook | Addon route → `payment_webhooks.py` | Marks order `paid` |
| Order status → paid/shipped/delivered | `notifications.py` | First enabled `NotificationAddon` |
| Order tracking on shipped emails | `notifications.py` | Core `Order.tracking_*` fields (manual admin entry) |
| Lifecycle marketing fan-out | `lifecycle_events.py` | `ToolAddon.on_lifecycle_event()` |
| Commerce measurement (purchase) | `tool_discovery.py` | `ToolAddon.on_commerce_event()` |
| Storefront tool scripts | `tool_discovery.py` | `ToolAddon.list_storefront_scripts()` → `storefront/config.tools` |
| Abandoned cart job | `abandoned_cart.py` | Core notification + lifecycle; CRM tools via `cart.abandoned` |
| Product search | `product_search.py` | Core ILIKE; optional `ToolAddon.search_products()` |
| Order status → paid (supplier-linked variants) | `fulfillment.py` | `SupplierAddon.create_order()` per variant assignment |
| Variant supplier linkage | `product_variants.py`, `suppliers.py` | `supplier_assignment_from_variant()`; addon hooks |
| Catalog sync | `supplier_catalog_sync.py` | `SupplierAddon.fetch_catalog_for_import()` |
| Storefront SSO metadata | `sso_discovery.py` | `ToolAddon.list_public_providers()` |
| Third-party tax at checkout | `tax_discovery.py` | `ToolAddon.quote_tax()` (falls back to Site Settings) |

## Related docs

- [Addon development guide](../addons/README.md)
- [Database backends](../../docs/DATABASE.md)
- [Admin panel](../admin/README.md)
