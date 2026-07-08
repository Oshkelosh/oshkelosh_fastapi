# Oshkelosh documentation

Developer documentation for the Oshkelosh modular e-commerce backend.

## Start here

| I want to… | Read |
|------------|------|
| Understand core vs addon responsibilities | [app/addons/README.md](../app/addons/README.md#core-vs-addon-responsibilities) |
| Understand the whole plugin system | [app/addons/README.md](../app/addons/README.md) |
| Build or customize a storefront SPA | [app/addons/frontends/README.md](../app/addons/frontends/README.md) |
| Integrate a payment provider | [app/addons/payments/README.md](../app/addons/payments/README.md) |
| Integrate a print-on-demand / supplier | [app/addons/suppliers/README.md](../app/addons/suppliers/README.md) (product + variant model) |
| Send transactional email | [app/addons/notifications/README.md](../app/addons/notifications/README.md) |
| Add analytics, A/B testing, or other shop tools | [app/addons/tools/README.md](../app/addons/tools/README.md) |
| Explore HTTP endpoints and schemas | [docs/api/OPENAPI.md](api/OPENAPI.md) |
| Understand API/admin surfaces | [app/api/README.md](../app/api/README.md) |
| Review security assumptions | [SECURITY.md](SECURITY.md) |
| Understand database backends | [DATABASE.md](DATABASE.md) |
| Run the project locally | [README.md](../README.md) (repository root) |

## Two configuration layers (storefront)

Oshkelosh separates **site-wide** settings from **frontend-specific** settings:

| Layer | Storage | Admin UI | Consumed by |
|-------|---------|----------|-------------|
| Site-wide | `site_settings` table | `/admin/settings` | SPA, admin header, emails, checkout tax/shipping rules |
| Frontend addon | `addon_configs` table | `/admin/addons` + `/admin/frontends/{id}` | Active SPA only |

See [app/addons/frontends/README.md](../app/addons/frontends/README.md) for the SPA bootstrap contract.

## API discovery

With the server running (`uvicorn app.main:app --reload`):

- **Swagger UI:** http://localhost:8000/docs
- **ReDoc:** http://localhost:8000/redoc
- **OpenAPI JSON:** http://localhost:8000/openapi.json

Export a copy to the repo:

```bash
python scripts/export_openapi.py
# writes docs/api/openapi.json
```

## Maintenance entrypoints

Recurring maintenance is not fully in-process. The app does two things today:

- Startup runs stale pending-order cleanup once as defense-in-depth.
- Automation should call admin JSON maintenance endpoints on a schedule:
  - `POST /api/v1/admin/jobs/abandoned-cart`
  - `POST /api/v1/admin/jobs/pending-orders`

See [app/api/README.md](../app/api/README.md) and [DATABASE.md](DATABASE.md) for the operational expectations.

## Repository layout (plugins)

```
app/addons/
├── README.md           ← plugin development (all categories)
├── base.py             ← BaseAddon
├── registry.py         ← auto-discovery
├── mount.py            ← route mounting + OpenAPI tags
├── frontends/          ← storefront SPAs
├── payments/           ← Stripe, etc.
├── suppliers/          ← Printful, etc.
├── notifications/      ← Postmark email, etc.
└── tools/              ← Analytics, A/B testing, etc.
```

Core commerce APIs live under `app/api/v1/routers/`. Products use a **product + variant** model — cart and orders reference `variant_id`; see [DATABASE.md](DATABASE.md#catalog-products-and-variants) and [suppliers README](../app/addons/suppliers/README.md#product-and-variant-model). Plugins extend the app without modifying core routers when possible — **core orchestrates, addons implement** (see [Core vs addon responsibilities](../app/addons/README.md#core-vs-addon-responsibilities)).

## Reading order for new contributors

1. [Repository README](../README.md) — install, run, deployment profiles, admin addon install
2. [Plugin overview](../app/addons/README.md) — how addons are discovered, mounted, and configured
3. Category guide for what you are building (frontend, payment, supplier, notification, or tool)
4. [OpenAPI guide](api/OPENAPI.md) — HTTP tags, storefront schemas, checkout sequence

## Site settings vs addon config

| What | Example fields | Where |
|------|----------------|-------|
| Site-wide branding | `store_name`, `primary_color`, `logo_url` | `/admin/settings` → `GET /api/v1/storefront/config` → `site` |
| Tax & shipping rules | `tax_rate_bps`, `shipping_mode`, zones JSON | `/admin/settings` → `checkout_pricing.py` at order create |
| Addon credentials | Stripe secret key, Postmark token | `/admin/payments/stripe`, etc. |
| Frontend-only UI | `layout`, `products_per_page` | `/admin/frontends/{id}` → `frontend.config` |

Keep store name and colors in **site settings** so they stay consistent when you switch frontend themes.
