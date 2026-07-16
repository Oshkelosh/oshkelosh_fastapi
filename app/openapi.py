"""OpenAPI metadata for Swagger UI, ReDoc, and exported ``openapi.json``."""

from __future__ import annotations

OPENAPI_TAGS: list[dict] = [
    {
        "name": "storefront",
        "description": (
            "Public storefront bootstrap API. Used by SPAs to load site-wide branding "
            "and active frontend-addon settings. See `app/addons/frontends/README.md`."
        ),
    },
    {
        "name": "auth",
        "description": "Customer registration, login, and JWT token refresh.",
    },
    {
        "name": "products",
        "description": "Published product catalog for the storefront.",
    },
    {
        "name": "categories",
        "description": "Product category tree.",
    },
    {
        "name": "cart",
        "description": "Authenticated shopping cart operations.",
    },
    {
        "name": "orders",
        "description": (
            "Order lifecycle: create from cart, list, cancel, and checkout via the "
            "enabled payment addon."
        ),
    },
    {
        "name": "media",
        "description": "Media upload and signed URL helpers (R2 or local storage).",
    },
    {
        "name": "admin",
        "description": "JSON admin API (JWT + admin role). Complements the HTML admin at `/admin`.",
    },
    {
        "name": "addons-suppliers",
        "description": (
            "Supplier addon HTTP endpoints (e.g. Printful catalog). "
            "See `app/addons/suppliers/README.md`."
        ),
    },
    {
        "name": "addons-payments",
        "description": (
            "Payment addon endpoints (e.g. Stripe checkout and webhooks). "
            "Prefer `POST /api/v1/orders/{id}/checkout` for generic checkout. "
            "See `app/addons/payments/README.md`."
        ),
    },
    {
        "name": "addons-notifications",
        "description": (
            "Notification addon endpoints. Order emails are triggered by core commerce, "
            "not these routes. See `app/addons/notifications/README.md`."
        ),
    },
    {
        "name": "addons-frontends",
        "description": (
            "Optional API routes contributed by frontend addons. Static assets are "
            "served at `/`, not documented here. See `app/addons/frontends/README.md`."
        ),
    },
    {
        "name": "internal",
        "description": "Health and readiness probes (non-versioned).",
    },
]

OPENAPI_DESCRIPTION = """
# Oshkelosh API

Modular e-commerce backend: core REST API plus **pluggable addons** for suppliers,
payments, notifications, and storefront frontends.

## Documentation (repository paths)

| Topic | Path |
|-------|------|
| Documentation index | `docs/README.md` |
| All plugins (overview) | `app/addons/README.md` |
| Storefront / SPA development | `app/addons/frontends/README.md` |
| Payment processors | `app/addons/payments/README.md` |
| Suppliers / fulfillment | `app/addons/suppliers/README.md` |
| Email / notifications | `app/addons/notifications/README.md` |
| OpenAPI reference | `docs/api/OPENAPI.md` |

## Authentication

Most customer endpoints require:

```
Authorization: Bearer <access_token>
```

Obtain tokens via `POST /api/v1/auth/login` or `POST /api/v1/auth/register`
(register returns a JWT session plus the user profile). Email verification is
optional after signup and never blocks shopping.

Admin JSON endpoints require a user with `is_admin=true`.

## Storefront SPA contract

1. Load branding: `GET /api/v1/storefront/config`
2. Optional early CSS: `GET /api/v1/storefront/theme.css`
3. Use core APIs for catalog, cart, orders, checkout

## Addon routes

Addon paths follow:

- **API:** `/api/v1/{category}s/{addon_id}/...` (example: `/api/v1/payments/stripe/checkout`)
- **Admin HTML:** `/admin/{category}s/{addon_id}/...` (configure credentials and options)

Enable and configure addons in the admin panel under Suppliers, Payments, Frontends, or Tools.
""".strip()
