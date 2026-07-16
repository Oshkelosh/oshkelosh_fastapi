# Plugin (addon) development guide

Oshkelosh extends core e-commerce through **addons**: self-contained Python packages under `app/addons/<category>/<name>/`. The registry discovers them at import time; enabled addons are loaded from the database on startup.

## Core vs addon responsibilities

Oshkelosh keeps the **core as light as possible**. Core orchestrates commerce; addons implement provider-specific behavior.

| Core owns | Addons own |
|-----------|------------|
| Commerce lifecycle (orders, cart, checkout, status transitions) | Provider API clients, OAuth flows, webhooks |
| Domain models (`User`, `Product`, `ProductVariant`, `Order`, `ManualSupplier`) | Catalog normalization and provider order APIs |
| Registry, discovery, route mounting, ZIP install | Variant supplier field validation and admin form hints |
| Generic orchestration at documented seams (see below) | Provider admin UI, config schemas, credentials |
| Shared cross-boundary schemas (`SupplierCatalogProduct`, `SupplierCatalogVariant`, etc.) | Per-provider fulfillment and sync logic |

**Rule of thumb:** adding a new supplier, payment processor, or tool should **not** require editing `app/services/*.py` with provider name checks. Extend the matching addon ABC (`SupplierAddon`, `PaymentAddon`, `ToolAddon`) and register routes instead.

## Categories

| Category | Base class | Only one active? | Guide |
|----------|------------|------------------|--------|
| `frontend` | `FrontendAddon` | **Yes** | [frontends/README.md](frontends/README.md) |
| `payment` | `PaymentAddon` | **Yes** (recommended) | [payments/README.md](payments/README.md) |
| `supplier` | `SupplierAddon` | No (per-variant supplier fields) | [suppliers/README.md](suppliers/README.md) — see **Product and variant model** |
| `notification` | `NotificationAddon` | **Yes** (recommended) | [notifications/README.md](notifications/README.md) |
| `tool` | `ToolAddon` | No | [tools/README.md](tools/README.md) |

## Architecture

```
app/addons/<category>/<addon_name>/
├── .gitignore           # each addon is its own Git repo (local clone for dev)
├── __init__.py          # package marker
├── addon.py             # main class (required for discovery)
├── routes.py            # optional API + admin routers
├── templates/           # optional Jinja admin UI
├── static/              # optional admin static files
├── tests/               # unit tests (config, clients, catalog normalizers)
└── dist/                # frontends only: built SPA
```

**Discovery** ([`registry.py`](registry.py)):

1. Scans `app/addons/*/*/` directories
2. Imports `addon.py` if present
3. Registers concrete subclasses of `BaseAddon`

**Runtime** ([`mount.py`](mount.py)):

- Public API routers → `/api/v1{api_mount_prefix}/...`
- Admin routers → `/admin{admin_mount_prefix}/...`
- OpenAPI tag → `addons-{category}` (e.g. `addons-payments`)

**Configuration** ([`app/services/addons.py`](../services/addons.py)):

- Persisted in `addon_configs` table
- `persist_addon_config(session, addon_id, config, enabled)` syncs DB + in-memory registry
- Enabling a `frontend` or `payment` addon disables others in that category

## Minimal addon checklist

1. **Pick a category** and inherit the matching ABC (or `BaseAddon` for new categories).
2. **Set identity** on the class:
   - `addon_id` — unique string (`"stripe"`, `"default"`)
   - `addon_name`, `addon_description`, `version`
   - `addon_category` — must match folder category
3. **Define `config_schema()`** as a `@classmethod` returning a Pydantic model.
4. **Implement lifecycle:**
   - `async def initialize(self, config: dict)` — open clients and runtime state
   - `async def shutdown(self)` — cleanup
   - `async def validate_config(self, config: dict)` — verify credentials and permissions when a `SecretStr` field changes (see **Credential validation** below)
5. **Optional routers:**
   - `get_routers()` → public REST under `/api/v1/...`
   - `get_admin_routes()` → admin HTML under `/admin/...`
6. **Add `.gitignore`** — each addon package is tracked in its own Git repo; ignore `__pycache__/`, local `.env`, and editor caches (frontends also ignore `node_modules/`, `dist/`, etc.).
7. **Use structured logging** — import from [`log.py`](log.py); log init and recoverable errors with a `[Provider]` prefix (see **Logging** below).
8. **Enable in admin** under the matching category list (Suppliers, Payments, Frontends, Tools) and fill configuration.

## Installing addons

Addon packages are installed from the **admin panel** — **Dashboard → Install addon** (ZIP upload or HTTPS URL). Packages land in `app/addons/<category>/<addon_id>/` and are discovered after a **full server restart** (or automatically in dev with `uvicorn --reload`).

Built-in addons that ship with the host repo: `manual` supplier and `sso` tool. All other addons (storefront, payments, suppliers, notifications) are installed via the admin panel in production and on fresh deploys.

### Maintainers: local clone workflow (development only)

Each non-built-in addon package lives in its **own Git repository**. For local development, clone it into the matching category path. The host repo does **not** track these packages (and must not use Git submodules). Production and fresh deploys install addons **only** via the admin dashboard (ZIP or HTTPS URL).

```bash
git clone git@github.com:Oshkelosh/stripe.git app/addons/payments/stripe
git clone git@github.com:Oshkelosh/default_frontend.git app/addons/frontends/default
cd app/addons/frontends/default && git checkout dev
```

Category-level `.gitignore` rules (`*/`, with exceptions like `!manual/` and `!sso/`) keep cloned addon dirs out of the host index. From inside a cloned addon directory, `git status` and `git rev-parse --show-toplevel` refer to the **addon** repo (nested `.git`). From the host root, `git status` is the main repo; ignored addon dirs do not appear as host changes. Admin ZIP installs without a nested `.git` are not separate repos — `git status` there falls through to the host.

**Do not** add addons with `git submodule add`. If an older checkout still has leftover submodule config:

```bash
git config --local --get-regexp '^submodule\.'   # list leftovers
# remove matching submodule.* keys from .git/config, delete .git/modules/<path> if present
```

Every addon repo should commit its own `.gitignore` at the package root (Python addons: caches, local `.env`, editor files; frontends: also `node_modules/` and `.svelte-kit/`). Frontend packages that distribute via GitHub source archives should **commit** `dist/` (do not gitignore it).

**Checklist for `default_frontend` (separate repo):**

1. Develop the SPA in `source/` (`npm run dev`).
2. Keep `oshkelosh-addon.json` at the repo root and commit a built `dist/` (`cd source && npm run build`).
3. Distribute via Admin → Install addon using the raw GitHub archive URL (no separate release required):
   `https://github.com/Oshkelosh/default_frontend/archive/refs/heads/main.zip`

Expected **shippable addon package layout** (repo root = addon package):

```
.gitignore
oshkelosh-addon.json
__init__.py
addon.py
routes.py
templates/
dist/          # frontends only — committed for ZIP / GitHub archive install
README.md
```

## Distributable addon packages (ZIP install)

### ZIP layout

Accepted layouts (manifest must appear exactly once):

1. Nested category path (singular **or** plural category folder):

```
<category>/<addon_id>/          # e.g. frontend/default/ or frontends/default/
  oshkelosh-addon.json
  __init__.py
  addon.py
  routes.py              # optional
  templates/ static/ dist/  # optional (dist/ required for frontends)
```

2. Flat addon root (manifest at ZIP root).

3. GitHub source archive: a single top-level wrapper folder (e.g. `default_frontend-main/`) containing the addon package. The wrapper name need not match `addon_id`.

Manifest `category` is singular (`frontend`, `tool`, …). The installer writes into the plural discovery directories (`frontends/`, `tools/`, …).

Include a `.gitignore` in addon repos (recommended for local clone development; not required for ZIP install validation).

### Manifest (`oshkelosh-addon.json`)

| Field | Required | Description |
|-------|----------|-------------|
| `addon_id` | yes | Lowercase identifier; must match folder name |
| `addon_name` | yes | Display name |
| `addon_description` | no | Short description |
| `category` | yes | Singular: `supplier`, `payment`, `notification`, `frontend`, or `tool` (installs under `suppliers/`, `payments/`, …) |
| `version` | yes | Addon semver string |
| `min_oshkelosh_version` | yes | Minimum host version (compare to `APP_VERSION`) |
| `max_oshkelosh_version` | no | Maximum supported host version |
| `python_requires` | no | PEP 440 specifier (default `>=3.11`) |
| `source_url` | no | HTTPS URL used by Admin → Update (GitHub repo or ZIP). Set automatically on URL install. |

Example:

```json
{
  "addon_id": "plausible",
  "addon_name": "Plausible Analytics",
  "addon_description": "Privacy-friendly analytics",
  "category": "tool",
  "version": "1.0.0",
  "min_oshkelosh_version": "0.1.0",
  "python_requires": ">=3.11"
}
```

Install validates manifest fields, required files, version compatibility, that `addon.py` defines exactly one concrete `BaseAddon` subclass matching the manifest, and that frontend addons include a built `dist/index.html`.

### Restart flag and watcher

After a successful install, the app writes an atomic flag file to `data/restart.flag` by default (JSON or one-line text). An external watcher should restart the app and remove the flag — the app does not restart itself.

Disable the flag with `ADDON_INSTALL_RESTART_FLAG_FILE=` in `.env`. Override the path or format:

```bash
ADDON_INSTALL_RESTART_FLAG_FILE=data/restart.flag
ADDON_INSTALL_RESTART_FLAG_FORMAT=json
```

Run the bundled watcher in a separate terminal or process:

```bash
# Production (systemd)
ADDON_INSTALL_RESTART_COMMAND="systemctl restart oshkelosh" \
  python scripts/watch_addon_restart.py

# Local dev (start server with scripts/run_dev.sh, then in another terminal)
ADDON_INSTALL_RESTART_COMMAND='kill -HUP $(cat .oshkelosh.pid)' \
  python scripts/watch_addon_restart.py
```

With `uvicorn --reload`, file changes under `app/addons/` may reload automatically; the watcher is mainly for deployments without reload.

Other install settings: `ADDON_INSTALL_MAX_BYTES` (default 25 MB), `ADDON_INSTALL_ALLOWED_HOSTS` (comma-separated HTTPS host allowlist for URL installs).

**URL install:** paste either a direct HTTPS ZIP URL or a bare GitHub repository URL such as `https://github.com/Oshkelosh/stripe`. Repo page URLs are expanded automatically to `https://github.com/Oshkelosh/stripe/archive/refs/heads/main.zip`.

## BaseAddon contract

```python
from app.addons.base import BaseAddon

class MyAddon(BaseAddon):
    addon_id = "my_addon"
    addon_name = "My Addon"
    addon_description = "What it does"
    addon_category = "payment"  # match directory category
    version = "1.0.0"

    @classmethod
    def config_schema(cls):
        return MyConfigModel

    async def initialize(self, config: dict): ...
    async def shutdown(self): ...
```

### Mount prefixes (override if needed)

| Method | Default | Example |
|--------|---------|---------|
| `api_mount_prefix()` | `/{category}s/{addon_id}` | `/payments/stripe` |
| `admin_mount_prefix()` | `/{category}s/{addon_id}` | `/payments/stripe` |

Full API path: `/api/v1` + prefix + route path.

## Configuration schema

Use Pydantic v2 with explicit fields and `Field(description=...)` — descriptions appear in code docs and help future OpenAPI extension.

```python
from pydantic import BaseModel, Field, SecretStr

class MyConfig(BaseModel):
    api_key: SecretStr = Field(description="Provider API key")
    webhook_secret: SecretStr = Field(description="Webhook signing secret")
```

Secrets are stored in `addon_configs.config` JSON. Admin forms should redact secrets on display using `redact_secret_values()` from `admin_helpers`.

### Credential validation

When an admin saves config and a `SecretStr` field changes, core calls `validate_config()` before persisting. Implement it in every addon package that stores secrets:

1. **Authentic** — the provider recognizes the credential (401 → invalid key message).
2. **Authorized** — the credential has permissions the addon needs (403 / scope errors → permission message).

```python
from app.core.exceptions import ValidationError

async def validate_config(self, config: dict) -> None:
    model = self.config_schema()(**config)
    api_key = model.api_key.get_secret_value()
    if not api_key:
        return
    try:
        await self._client.verify(api_key)  # lightweight read-only probe
    except AuthError as exc:
        raise ValidationError(message="Invalid API key — check your credentials") from exc
    except PermissionError as exc:
        raise ValidationError(
            message="API key is valid but missing required permissions: catalog:read"
        ) from exc
```

List required provider permissions/scopes in the addon `README.md`. OAuth client secrets (SSO) cannot be fully verified without a user login — validate issuer reachability and required scopes instead.

Addons without secrets inherit the default no-op `validate_config`.

### Rendering admin templates

Always use `render_addon_admin_page()` — never pass `flash` or `flash_type` separately after `**_common_ctx(...)`, which causes a Jinja `TypeError` and surfaces as `internal_error` JSON:

```python
from app.addons.admin_helpers import make_addon_jinja_env, render_addon_admin_page

jinja_env = make_addon_jinja_env(Path(__file__).resolve().parent / "templates")

return HTMLResponse(
    content=render_addon_admin_page(
        jinja_env,
        request,
        "my_config.html",
        "My Addon Settings",
        addon=addon,
        config=config,
    ),
)
```

On save errors, pass `flash=` and `flash_type="error"` to the same helper only.

Every mutating HTML form must include a CSRF token (import from the shared admin base):

```jinja
{% from "_macros.html" import csrf_field with context %}
...
<form method="post" action="...">
  {{ csrf_field() }}
```

The `with context` import is required so the macro can read `csrf_token` from the page context.

POST handlers should call `require_addon_csrf(request, str(form.get("csrf_token", "")))` before any write.

### Saving config from admin routes

Use the shared helper:

```python
from app.addons.admin_helpers import save_addon_from_form

await save_addon_from_form(
    db,
    "my_addon",
    config_dict,
    enabled=True,
    redirect_url="/admin/payments/my_addon",
    flash_message="Saved",
)
```

Or call `persist_addon_config()` directly from your own code paths.

## How core commerce uses addons

| Event | Service | Addon used |
|-------|---------|------------|
| Order creation (tax & shipping) | `app/services/checkout_pricing.py` | Site Settings rules; optional `ToolAddon.quote_tax()`; optional `SupplierAddon.quote_shipping()` |
| Checkout | `POST /api/v1/orders/{id}/checkout` | First enabled `PaymentAddon` |
| Payment webhook | Addon route (e.g. Stripe) | Marks order `paid` |
| Order status → paid/shipped/delivered | `app/services/notifications.py` | First enabled `NotificationAddon` |
| Order tracking on shipped emails | `app/services/notifications.py` | Core `Order.tracking_*` fields (manual admin entry) |
| Lifecycle marketing fan-out | `app/services/lifecycle_events.py` | `ToolAddon.on_lifecycle_event()` |
| Commerce measurement (purchase) | `app/services/tool_discovery.py` | `ToolAddon.on_commerce_event()` |
| Storefront tool scripts | `app/services/tool_discovery.py` | `ToolAddon.list_storefront_scripts()` → `storefront/config.tools` |
| Abandoned cart job | `app/services/abandoned_cart.py` | Core notification + lifecycle; CRM tools via `cart.abandoned` |
| Product search | `app/services/product_search.py` | Core ILIKE; optional `ToolAddon.search_products()` |
| Order status → paid (supplier-linked variants) | `app/services/fulfillment.py` | `SupplierAddon.create_order()` per variant assignment |
| Variant supplier linkage | `app/services/product_variants.py`, `app/services/suppliers.py` | `supplier_assignment_from_variant()`; addon hooks for legacy tags and admin forms |
| Catalog sync | `app/services/supplier_catalog_sync.py` | `SupplierAddon.fetch_catalog_for_import()` → `SupplierCatalogProduct[]` |
| Storefront SSO metadata | `app/services/sso_discovery.py` | `ToolAddon.list_public_providers()` |
| Third-party tax at checkout | `app/services/tax_discovery.py` | `ToolAddon.quote_tax()` (falls back to Site Settings) |

You do **not** need to patch core routers if you hook through these flows or expose provider-specific routes.

## Admin UI options

1. **Dedicated admin routes** (recommended for complex config)  
   Return `get_admin_routes()` with Jinja templates under `templates/`.

2. **Generic JSON form**  
   Omit `get_admin_routes()`. Admins use `/admin/addons/{addon_id}/configure`.

**Sidebar links:** Override `get_admin_nav_items()` to return `AdminNavItem(label=..., url=..., section=...)` entries. Enabled addons are aggregated in the admin layout (`base.html`) below core navigation.

**Host compatibility:** Set `min_host_version` on your `BaseAddon` subclass (default `"0.0.0"`). `AddonRegistry.enable_async()` and startup refuse to enable when `APP_VERSION` is older than the addon requires (same semver rules as install manifests).

3. **Enable/disable only**  
   List appears on `/admin/addons`; secrets live in `addon_configs` (managed via the admin UI), not in `.env`.

## Logging

Use [`app/addons/log.py`](log.py) in addon code — do not import `loguru` directly in addon packages.

```python
from app.addons.log import info, label_for, warning

class StripeAddon(PaymentAddon):
    log_label: str = "Stripe"  # optional; defaults to addon_name

    async def initialize(self, config: dict) -> None:
        ...
        info(label_for(self), "Initialized (publishable_key={}…)", self._publishable_key[:10])

    async def create_payment(self, ...):
        try:
            ...
        except Exception as exc:
            warning(label_for(self), "create_payment error: {}", exc)
```

| Level | When |
|-------|------|
| `info` | Addon initialized, webhook event type received, catalog sync summary |
| `warning` | Expected API/provider failures (HTTP errors, validation) |
| `exception` | Unexpected errors in shared route handlers (includes stack trace) |

Rules:

- Set `log_label` on the class when the log prefix should differ from `addon_name` (e.g. `log_label = "Manual"`).
- Never log secrets, tokens, authorization codes, or raw webhook payloads.
- Lifecycle enable/disable is logged by [`registry.py`](registry.py); per-addon `shutdown()` does not need a log line.

## Testing addons

**Unit tests** live in each addon package under `tests/` (config schemas, API client mappers, catalog normalizers). **Integration and cross-addon smoke tests** stay in the host [`tests/`](../../tests/) directory (registry, install pipeline, admin page smoke, HTTP flows).

```bash
pytest                                              # full suite (host + all addons)
pytest app/addons/payments/stripe/tests -q          # one addon
pytest tests/test_addons.py tests/test_addon_integration.py -q   # host addon wiring only
```

In a standalone addon repo (local clone), install the host as an editable dev dependency and run `pytest tests/` from the addon root:

```bash
pip install -e /path/to/oshkelosh_fastapi[dev]
pytest tests/
```

Minimal discovery check:

```python
from app.addons.registry import AddonRegistry

registry = AddonRegistry()
registry.discover()
assert "my_addon" in [m["addon_id"] for m in registry.list_addons()]
```

Host integration tests: enable addon via `persist_addon_config`, call routes with `httpx.AsyncClient`, mock external APIs.

See [`tests/test_addons.py`](../../tests/test_addons.py) and [`tests/test_addon_integration.py`](../../tests/test_addon_integration.py).

## OpenAPI

Addon HTTP routes are tagged `addons-{category}` in Swagger. See [docs/api/OPENAPI.md](../../docs/api/OPENAPI.md).

Export spec: `python scripts/export_openapi.py`

## Category-specific guides

- [Frontends / SPAs](frontends/README.md)
- [Payments](payments/README.md)
- [Suppliers](suppliers/README.md)
- [Notifications](notifications/README.md)
- [Tools](tools/README.md)

## Included reference addons

Each addon package includes its own `README.md` with provider-specific config, routes, and setup. Category READMEs cover shared patterns only.

| ID | Category | Package | Docs |
|----|----------|---------|------|
| `default` | frontend | `frontends/default/` | [README](frontends/default/README.md) |
| `postmark`, `smtp`, `resend`, `sendgrid`, `mailgun`, `ses` | notification | `notifications/<id>/` | `<id>/README.md` when installed |
| `twilio`, `vonage`, `messagebird` | notification | `notifications/<id>/` | `<id>/README.md` when installed |
| `fcm`, `onesignal`, `pusher_beams` | notification | `notifications/<id>/` | `<id>/README.md` when installed |
| `sso` | tool | `tools/sso/` | [README](tools/sso/README.md) |
| `manual` | supplier | `suppliers/manual/` | [README](suppliers/manual/README.md) |
| `stripe`, `paypal`, `mangopay`, `adyen`, `checkout`, `mollie`, `worldpay`, `airwallex`, `rapyd` | payment | `payments/<id>/` | `<id>/README.md` when installed |
| `printful`, `printify`, `gelato`, `prodigi`, `gooten`, `cjdropshipping`, `customcat`, `spreadconnect`, `podbase` | supplier | `suppliers/<id>/` | `<id>/README.md` when installed |

Install addons from the admin dashboard (ZIP/URL), or use a local `git clone` into `app/addons/<category>/<id>/` for development.
