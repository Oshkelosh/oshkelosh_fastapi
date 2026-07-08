# Database backends

Oshkelosh supports three database backends, selected via `DATABASE_BACKEND` or the `DEPLOYMENT_PROFILE` preset in [`.env`](../.env.example).

| Backend | Typical use | Connection |
|---------|-------------|------------|
| `sqlite` | Local development | File at `data/oshkelosh.db` |
| `d1_http` | Docker/VPS/Railway with Cloudflare D1 HTTP API | `D1_ACCOUNT_ID`, `D1_DATABASE_ID`, `D1_API_TOKEN` |
| `d1_binding` | Cloudflare Workers (in-process D1 binding) | Worker entrypoint calls `set_d1_binding()` |

## Schema on fresh install

There is **no Alembic-style migration runner** for application models. New environments get tables from SQLModel `create_all` during bootstrap ([`app/services/bootstrap.py`](../app/services/bootstrap.py)).

Optional SQL files under [`migrations/d1/`](../migrations/d1/) are supplemental (indexes, idempotency DDL) for future D1/wrangler deploys. They are tracked in the `schema_migrations` table when applied manually — that table records **which SQL files ran**, not automatic ORM model sync.

Do not plan `ALTER TABLE` backfills against production data in this project phase; treat schema changes as bootstrap-only until a production database exists.

## ORM usage conventions

**Avoid lazy loads.** Async sessions do not support implicit relationship loading. Use explicit helpers and queries:

- `load_cart_items`, `load_order_items` in [`app/services/commerce.py`](../app/services/commerce.py)
- `select(Model).where(...)` with `await session.execute`

After raw SQL `UPDATE` statements (inventory reservation), call `session.refresh(instance)` so the ORM identity map matches the database — see the module docstring in `commerce.py`.

## Catalog: products and variants

Sellable catalog data is split across two tables:

| Table | Role |
|-------|------|
| `products` | Base listing — name, slug, description, SEO, `options` (creator specs), denormalized list price/stock |
| `product_variants` | Purchasable SKU — price, inventory, `attributes` (picker hints), supplier IDs |

**Cart and orders** reference `variant_id` on `cart_items` and `order_items`. Order history stores a `variant_snapshot` JSON on each line.

**Categories** link products via `products.category_id` → `categories.id` (optional; `ON DELETE SET NULL`).

**Images** live only in `product_images` (shared when `variant_id` is null, or tied to a variant). API `ProductRead.images` is assembled from those rows at read time — add images via admin upload, supplier sync, or `POST /api/v1/products/{id}/images`.

**Supplier sync** sets `products.supplier_external_product_key` (parent design) and per-variant `supplier_external_key` / `supplier_*` fields. See [Supplier addon development](../app/addons/suppliers/README.md#product-and-variant-model).

Listing endpoints expose denormalized `products.price_cents`, `inventory_quantity`, and `has_variants` (refreshed from active variants). Product detail (`ProductDetailRead`) includes a `variants[]` array.

**SEO:** Public product URLs are canonical per design (`/products/{slug}`). Server-rendered meta tags and JSON-LD use `AggregateOffer` (`lowPrice` / `highPrice`) when `has_variants` is true; otherwise a single `Offer`. See [app/storefront/seo.py](../app/storefront/seo.py).

## SQLite specifics

- Default local backend; file created automatically when the parent directory exists.
- Inventory updates use `sqlalchemy.text()` when `execute_raw` is not available on the session.

## D1 HTTP specifics

[`D1HTTPAsyncSession`](../app/db/backends/d1_http_session.py):

- Queues writes until `flush()`; `flush()` sends a **batch** via `D1Connection.batch_query()`.
- Call `mark_dirty(instance)` (or `mark_instance_dirty`) after in-place mutations so the session tracks changes.
- `rollback()` clears the write queue only; remote D1 state is not rolled back transactionally.

## D1 binding specifics

Used when the app runs inside a Cloudflare Worker with an in-process D1 binding. Requires `set_d1_binding()` from the Worker entrypoint in production.
