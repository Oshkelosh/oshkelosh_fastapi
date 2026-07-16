# Frontend addon development

A **frontend addon** is a pre-built SPA (static `dist/` folder) plus optional frontend-specific configuration. Only **one** frontend can be active; the app serves its `dist/` at `/` and exposes merged config at `GET /api/v1/storefront/config`.

Site-wide branding (name, logo, colors, fonts) lives in **Site Settings** (`/admin/settings`), not in the frontend addon schema.

## Quick start

1. Copy `default/` to `app/addons/frontends/my_theme/`
2. Build your React/Vue/Svelte app into `my_theme/dist/` (must include `index.html`)
3. Implement `MyThemeAddon(FrontendAddon)` in `addon.py`
4. Enable at **Admin → Addons** (disables other frontends)
5. Configure layout options at `/admin/frontends/my_theme`

## Configuration layers

```
┌─────────────────────────────────────────────────────────┐
│  GET /api/v1/storefront/config                          │
├─────────────────────────────────────────────────────────┤
│  site {          ← SiteSettings (all frontends share)   │
│    store_name, logo_url, primary_color, font_family, …  │
│  }                                                      │
│  frontend {      ← Active addon config_schema only      │
│    addon_id, version,                                   │
│    config { layout, products_per_page, … }              │
│  }                                                      │
└─────────────────────────────────────────────────────────┘
```

| Field source | Admin UI | In your SPA |
|--------------|----------|-------------|
| `site.*` | `/admin/settings` | `config.site.store_name`, etc. |
| `frontend.config.*` | `/admin/frontends/{addon_id}` | `config.frontend.config.layout`, etc. |

**Do not** duplicate `store_name` or colors in `config_schema()` — read them from `site`.

## SPA bootstrap contract (required)

Every frontend **must** load config on startup.

### 1. Optional early theme (recommended)

In `index.html`:

```html
<link rel="stylesheet" href="/api/v1/storefront/theme.css" />
<link rel="stylesheet" href="/assets/styles.css" />
```

### 2. Fetch merged config

```javascript
const response = await fetch("/api/v1/storefront/config");
if (!response.ok) {
  // 503 = no frontend enabled — show maintenance message
  throw new Error("Storefront unavailable");
}
const { site, frontend } = await response.json();
```

### 3. Apply site branding

```javascript
document.title = site.store_name;

document.documentElement.style.setProperty("--color-primary", site.primary_color);
document.documentElement.style.setProperty("--color-secondary", site.secondary_color);
document.documentElement.style.setProperty("--font-sans", site.font_family);

if (site.logo_url) {
  logoElement.innerHTML = `<img src="${site.logo_url}" alt="${site.store_name}" />`;
} else {
  logoElement.textContent = site.store_name;
}

if (site.favicon_url) {
  // set <link rel="icon" href="...">
}
```

### 4. Apply frontend-specific options

```javascript
const cfg = frontend.config;
document.body.classList.add(`layout-${cfg.layout ?? "grid"}`);
```

Reference implementation: [`default/dist/assets/app.js`](default/dist/assets/app.js).

## CSS variables

### Base (from site settings)

| Variable | Source | Set by |
|----------|--------|--------|
| `--color-primary` | `site.primary_color` | `theme.css` or JS |
| `--color-secondary` | `site.secondary_color` | `theme.css` or JS |
| `--font-sans` | `site.font_family` | `theme.css` or JS |
| `--color-on-primary` | contrast text for primary | JS (`+layout.svelte`) |
| `--color-on-secondary` | contrast text for secondary | JS (`+layout.svelte`) |

### Derived (computed in CSS via `color-mix`)

| Variable | Role |
|----------|------|
| `--color-primary-muted` / `--color-primary-subtle` / `--color-primary-hover` / `--color-primary-border` | Primary (action) tints and hover |
| `--color-secondary-muted` / `--color-secondary-subtle` / `--color-secondary-hover` / `--color-secondary-border` | Secondary (structure) tints and borders |

**Color roles:** use **primary** for actions (CTAs, prices, active states, link hover). Use **secondary** for structure chrome only — borders, subtle backgrounds, outline button borders — not body copy, headings, or default link text. Keep readable text on `--clr-text` and `--clr-muted`; neutrals are lightly harmonized with secondary.

Use these names in your stylesheets for consistency with the default theme.

## FrontendAddon API

```python
from pathlib import Path
from app.addons.frontends.base import FrontendAddon

class MyThemeAddon(FrontendAddon):
    addon_id = "my_theme"
    addon_name = "My Theme"
    addon_description = "Custom storefront layout"
    addon_category = "frontend"
    version = "1.0.0"

    @classmethod
    def config_schema(cls):
        return MyThemeConfig  # Pydantic — frontend-only fields

    async def initialize(self, config: dict): ...
    async def shutdown(self): ...

    def get_static_directory(self) -> str:
        return str(Path(__file__).parent / "dist")

    def get_admin_routes(self):  # optional
        from .routes import admin_router
        return [admin_router]
```

### Required: `get_static_directory()`

Must point to a directory containing:

```
dist/
├── index.html
└── assets/
    ├── app.js
    └── styles.css
```

The app mounts this folder at `/` with SPA fallback (`html=True`).

## Package layout

```
app/addons/frontends/my_theme/
├── .gitignore
├── __init__.py
├── addon.py
├── routes.py              # optional admin config form
├── templates/
│   └── my_theme_config.html
└── dist/                  # production build output
    ├── index.html
    └── assets/
```

## Build tooling notes

- Set your bundler **public path** to `/` (assets served from `/assets/...`).
- API calls go to `/api/v1/...` on the same origin (or configure CORS).
- Auth: store JWT from `POST /api/v1/auth/login`, send `Authorization: Bearer ...`.
- After building, reload the storefront in your browser — the server serves files from disk on each request.
- Installing a **new** frontend addon package still requires a server restart (addon discovery runs at startup).

## Switching frontends in admin

1. Open `/admin/addons`
2. Enable desired frontend (others in category auto-disable)
3. Configure frontend-specific options at `/admin/frontends/{addon_id}`
4. Set site branding at `/admin/settings` (applies to all frontends)
5. Reload the storefront `/` in your browser

Changes take effect immediately — no server restart required. The app resolves the active frontend per request via [`app/services/storefront_resolver.py`](../../services/storefront_resolver.py) (extension point for future A/B testing).

No code deploy required beyond having the addon package in the repo.

## OpenAPI (storefront tag)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/storefront/config` | Merged `site` + `frontend` JSON |
| GET | `/api/v1/storefront/theme.css` | CSS custom properties |

Schemas: [`schemas/storefront.py`](../../../schemas/storefront.py).  
Full reference: [docs/api/OPENAPI.md](../../../docs/api/OPENAPI.md).

## Core APIs your SPA will use

| Area | Endpoints |
|------|-----------|
| Auth | `POST /api/v1/auth/register`, `login`, `refresh` |
| Catalog | `GET /api/v1/products`, `GET /api/v1/products/by-slug/{slug}`, `GET /api/v1/categories` |
| Cart | `POST/GET/PATCH/DELETE /api/v1/cart/...` (auth) — **`variant_id` required** when adding items |
| Orders | `POST /api/v1/orders`, `GET /api/v1/orders/{id}` |
| Checkout | `POST /api/v1/orders/{id}/checkout` |

### Product variants (storefront contract)

- **List views** use `ProductRead` — `price` is the minimum active variant price; `has_variants: true` means show “From $X”.
- **Detail views** use `ProductDetailRead` — includes `variants[]` with per-variant price, stock, `attributes` (Size, Color), and images.
- **`options`** on the product are creator specs (material, care) — display-only, not a purchase picker.
- **Add to cart** always sends `{ product_id, variant_id, quantity }`. Single-variant products still have one row in `variants[]`.
- **Cart display** uses `variant_title` from enriched cart responses.

After hosted payment, customers return to `/orders/{id}?payment=return`. Handle that query param on the order detail page while the payment webhook confirms the order.

Browse Swagger at `/docs` when `DEBUG=true`.

## Reference addon

See [`default/README.md`](default/README.md) — SvelteKit storefront with catalog, auth, cart, checkout, orders, and SSO callback. Includes full bootstrap example and admin layout options.
