# OpenAPI reference

Oshkelosh exposes a machine-readable API contract at **`/openapi.json`**. Swagger UI (`/docs`) and ReDoc (`/redoc`) are available when `DEBUG=true`.

## Exporting `openapi.json`

```bash
# Server must be importable (venv active, deps installed)
python scripts/export_openapi.py
```

Output: [`openapi.json`](openapi.json) in this directory (git-tracked optional).

Or from a running server:

```bash
curl -s http://localhost:8000/openapi.json | jq . > docs/api/openapi.json
```

## Tag groups

Endpoints are grouped by OpenAPI **tags**. Tags map to subsystems:

| Tag | Prefix / area | Purpose |
|-----|----------------|---------|
| `storefront` | `/api/v1/storefront/*` | SPA bootstrap (`config`, `theme.css`) |
| `auth` | `/api/v1/auth/*` | Register, login, refresh |
| `products` | `/api/v1/products/*` | Catalog |
| `categories` | `/api/v1/categories/*` | Category tree |
| `cart` | `/api/v1/cart/*` | Shopping cart (auth required) |
| `orders` | `/api/v1/orders/*` | Orders + `POST .../checkout` |
| `media` | `/api/v1/...` | Uploads / media URLs |
| `admin` | `/api/v1/admin/*` | JSON admin API |
| `addons-suppliers` | `/api/v1/suppliers/{addon_id}/*` | Supplier plugin routes |
| `addons-payments` | `/api/v1/payments/{addon_id}/*` | Payment plugin routes |
| `addons-notifications` | `/api/v1/notifications/{addon_id}/*` | Notification plugin routes |
| `addons-frontends` | `/api/v1/frontends/{addon_id}/*` | Rare; static SPA is at `/` |
| `status` | `/api/v1/health` | API health |
| `internal` | `/health` | App health (non-versioned) |

Tag descriptions are defined in [`app/openapi.py`](../../app/openapi.py).

## Storefront schemas (SPA developers)

Documented under tag **`storefront`**:

### `GET /api/v1/storefront/config`

**200** — [`StorefrontConfigResponse`](../../schemas/storefront.py)

```json
{
  "site": {
    "store_name": "My Shop",
    "logo_url": "https://example.com/logo.png",
    "favicon_url": null,
    "primary_color": "#2563eb",
    "secondary_color": "#64748b",
    "font_family": "system-ui, sans-serif",
    "support_email": "help@example.com",
    "meta_description": "We sell great things."
  },
  "frontend": {
    "addon_id": "default",
    "addon_name": "Default Storefront",
    "version": "1.0.0",
    "config": {
      "layout": "grid",
      "products_per_page": 12,
      "show_category_nav": true
    }
  }
}
```

**503** — No frontend addon enabled (`detail` field).

### `GET /api/v1/storefront/theme.css`

**200** — `text/css` with `:root` variables:

- `--color-primary`
- `--color-secondary`
- `--font-sans`

## Core commerce flow (OpenAPI)

Typical authenticated checkout path:

1. `POST /api/v1/auth/login` → `access_token`
2. `GET /api/v1/products/{id}` or `GET /api/v1/products/by-slug/{slug}` → `ProductDetailRead` with `variants[]`
3. `POST /api/v1/cart/items` → add a line with `{ product_id, variant_id, quantity }`
4. `POST /api/v1/orders` → create pending order (line items carry `variant_id`)
5. `POST /api/v1/orders/{order_id}/checkout` → payment session (requires enabled **payment** addon)
6. Payment provider webhook → order status `paid` (addon-specific path, e.g. Stripe)

### Product and cart schemas

| Schema | Notes |
|--------|-------|
| `ProductRead` | List view — denormalized `price_cents`, `has_variants`, `options` (creator specs) |
| `ProductDetailRead` | Extends `ProductRead` with `variants: ProductVariantRead[]` |
| `ProductVariantRead` | `title`, `price`, `inventory_quantity`, `attributes`, per-variant `images` |
| `CartItemAdd` | Requires **`variant_id`** (not just `product_id`) |
| `CartItemWithPrice` | Includes `variant_title` for display |

Order line items include `variant_id` and a `variant_snapshot` object for historical display.

## Addon route naming

When an addon implements `get_routers()`, routes mount at:

```
{API_V1_PREFIX}/{category}s/{addon_id}/{route_path}
```

Examples:

| Addon | Example path |
|-------|----------------|
| Stripe | `POST /api/v1/payments/stripe/checkout` |
| Stripe webhook | `POST /api/v1/payments/stripe/webhook` |
| Printful | `GET /api/v1/suppliers/printful/products` |

Admin configuration UIs are **HTML** under `ADMIN_PREFIX` (default `/admin`). The current exported schema includes some of these HTML routes because they are mounted on the same FastAPI app; treat them as operator pages rather than JSON API contracts.

## Authentication in OpenAPI

Click **Authorize** in Swagger UI and paste:

```
Bearer <your_access_token>
```

Admin JSON routes require a user with `is_admin: true`.

## What is not in OpenAPI

- **Most HTML admin behavior** (`ADMIN_PREFIX/*`) is for forms and Jinja pages rather than programmatic JSON clients, even when routes appear in the exported schema.
- **Static storefront** (`/`, `/assets/*`) — served dynamically from the active frontend addon per request (see `app/services/storefront_resolver.py`)
- **Local media** (`/media/files/*`) — when `storage_backend=local`

## Related docs

- [Plugin overview](../../app/addons/README.md)
- [Frontend development](../../app/addons/frontends/README.md)
