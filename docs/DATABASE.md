# Database backends

Oshkelosh supports three database backends, selected via `DATABASE_BACKEND` or the `DEPLOYMENT_PROFILE` preset in [`.env`](../.env.example).

| Backend | Typical use | Connection |
|---------|-------------|------------|
| `sqlite` | Local development | File at `data/oshkelosh.db` |
| `d1_http` | Docker/VPS/Railway with Cloudflare D1 HTTP API | `D1_ACCOUNT_ID`, `D1_DATABASE_ID`, `D1_API_TOKEN` |
| `d1_binding` | Cloudflare Workers (in-process D1 binding) | Worker entrypoint calls `set_d1_binding()` |

## Schema on fresh install

There is **no Alembic-style model diff runner**. Fresh environments still get application tables from SQLModel bootstrap, but startup also applies tracked SQL files from [`migrations/d1/`](../migrations/d1/) for supplemental indexes, constraints, and bootstrap-only DDL.

The `schema_migrations` table records which migration files ran. Re-running startup is safe: already-applied SQL files are skipped.

Do not plan `ALTER TABLE` backfills against production data in this project phase; treat schema changes as bootstrap-only until a production database exists.

## Operations and recurring maintenance

Two cleanup paths matter operationally:

- **Abandoned cart reminders** via `POST /api/v1/admin/jobs/abandoned-cart`
- **Pending order cleanup** via `POST /api/v1/admin/jobs/pending-orders`

The FastAPI lifespan also runs pending-order cleanup once at startup, but that is only defense-in-depth. Production deployments should invoke the admin JSON maintenance endpoints from cron, a scheduler, or an external worker on a recurring cadence.

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
- Foreign-key enforcement is enabled explicitly (`PRAGMA foreign_keys=ON`) for app and test SQLite engines so `SET NULL` / cascade behavior matches production expectations.
- Inventory updates use `sqlalchemy.text()` when `execute_raw` is not available on the session.

## D1 HTTP specifics

[`D1HTTPAsyncSession`](../app/db/backends/d1_http_session.py):

- Queues writes until `flush()`; `flush()` sends a **batch** via `D1Connection.batch_query()`.
- Call `mark_dirty(instance)` (or `mark_instance_dirty`) after in-place mutations so the session tracks changes.
- `rollback()` clears the write queue only; remote D1 state is not rolled back transactionally.

Supplemental constraints and indexes added by `migrations/d1/*.sql` remain important here, especially idempotency and webhook uniqueness indexes that SQLModel does not fully express for the D1 HTTP emitter.

## D1 binding specifics

Used when the app runs inside a Cloudflare Worker with an in-process D1 binding. Requires `set_d1_binding()` from the Worker entrypoint in production.
