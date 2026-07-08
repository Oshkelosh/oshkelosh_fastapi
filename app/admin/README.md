# Admin panel

Oshkelosh exposes two admin surfaces that share domain models and services but differ in transport and auth.

## HTML admin vs REST admin API

| Surface | Prefix | Auth | Use case |
|---------|--------|------|----------|
| **HTML admin** | `/admin/*` | Signed httponly session cookie (`ADMIN_SESSION_SECRET`) | Browser UI: Jinja templates, forms, redirects |
| **REST admin API** | `/api/v1/admin/*` | Bearer JWT (`Authorization` header); user must have `is_admin=true` | Headless clients, scripts, SPA tooling |

Route modules live under [`routes/`](routes/): `auth`, `dashboard`, `products`, `categories`, `users`, `orders`, `settings`, `addons`, `audit`, `misc`. They are composed in [`routes/__init__.py`](routes/__init__.py).

The REST counterpart is [`app/api/v1/routers/admin.py`](../api/v1/routers/admin.py) — JSON CRUD for products, categories, users, orders, addons, dashboard stats, and supplier catalog sync.

Both paths call the same `app/services/*` helpers. Prefer the HTML panel for day-to-day shop management; use the REST API for automation or custom integrations.

### Products and variants (HTML admin)

**Admin → Products** manages base listing fields and a **variants table** on edit:

| Section | Purpose |
|---------|---------|
| Base product | Name, slug, description, status, category, shared images |
| Creator options | `products.options` JSON — display specs (not purchasable) |
| Variants | Per-SKU price, stock, attributes, supplier fields; synced variants are read-only |
| Create flow | Creates one default variant with optional supplier assignment |

Manual products can edit variant rows; supplier-synced products show variant data as read-only.

## CSRF pattern (HTML admin)

Mutating HTML forms require a CSRF token. The flow:

1. **Login** — [`session.py`](session.py) issues a signed session payload containing a random `csrf` claim.
2. **Per request** — [`require_admin_session`](routes/_deps.py) decodes the cookie, loads the admin user, and sets `request.state.csrf_token` from the session claim.
3. **Templates** — `_common_ctx()` passes `csrf_token` into every page; forms include `<input type="hidden" name="csrf_token" …>`.
4. **POST handlers** — accept `csrf_token: str = Form(...)`, then call `_require_csrf(request, csrf_token)` before any write.

A mismatch returns `403 Invalid CSRF token`. The REST admin API does not use CSRF (Bearer tokens only).

First-run setup at `/setup` uses a separate short-lived CSRF cookie (`_oshkelosh_setup_csrf`); see [`app/setup/routes.py`](../setup/routes.py).

## Addon admin UI

Payment, supplier, notification, and tool addons can mount admin routes under `/admin/{category}s/{addon_id}/`. Shared helpers live in [`app/addons/admin_helpers.py`](../addons/admin_helpers.py):

- `make_addon_jinja_env()` — resolves addon templates plus shared `base.html`
- `render_addon_admin_page()` — consistent layout, flash messages, CSRF in context
- `save_addon_from_form()` — persist config via `persist_addon_config`
- `redact_secret_values()` — mask secrets on config pages

Addon admin POST routes should call `require_addon_csrf()` (reuses the host session CSRF claim). See [app/addons/README.md](../addons/README.md#rendering-admin-templates).

## Related docs

- [Security assumptions](../../docs/SECURITY.md)
- [Addon development](../addons/README.md)
