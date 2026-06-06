# Plugin (addon) development guide

Oshkelosh extends core e-commerce through **addons**: self-contained Python packages under `app/addons/<category>/<name>/`. The registry discovers them at import time; enabled addons are loaded from the database on startup.

## Categories

| Category | Base class | Only one active? | Guide |
|----------|------------|------------------|--------|
| `frontend` | `FrontendAddon` | **Yes** | [frontends/README.md](frontends/README.md) |
| `payment` | `PaymentAddon` | **Yes** (recommended) | [payments/README.md](payments/README.md) |
| `supplier` | `SupplierAddon` | No (per-product tags) | [suppliers/README.md](suppliers/README.md) |
| `notification` | `NotificationAddon` | **Yes** (recommended) | [notifications/README.md](notifications/README.md) |
| `tool` | `ToolAddon` | No | [tools/README.md](tools/README.md) |

## Architecture

```
app/addons/<category>/<addon_name>/
├── __init__.py          # package marker
├── addon.py             # main class (required for discovery)
├── routes.py            # optional API + admin routers
├── templates/           # optional Jinja admin UI
├── static/              # optional admin static files
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
   - `async def initialize(self, config: dict)` — validate secrets, open clients
   - `async def shutdown(self)` — cleanup
5. **Optional routers:**
   - `get_routers()` → public REST under `/api/v1/...`
   - `get_admin_routes()` → admin HTML under `/admin/...`
6. **Enable in admin** under the matching category list (Suppliers, Payments, Frontends, Tools) and fill configuration.

## Distributable addon packages (ZIP install)

Admins can install addons from the **Dashboard → Install addon** card (ZIP upload or HTTPS URL). Packages land in `app/addons/<category>/<addon_id>/` and are discovered after a **full server restart** (or automatically in dev with `uvicorn --reload`).

### ZIP layout

```
<category>/<addon_id>/
  oshkelosh-addon.json
  __init__.py
  addon.py
  routes.py              # optional
  templates/ static/ dist/  # optional
```

Alternatively, the ZIP root may be the addon folder itself (manifest at the root) when `category` and `addon_id` in the manifest match the intended install path.

### Manifest (`oshkelosh-addon.json`)

| Field | Required | Description |
|-------|----------|-------------|
| `addon_id` | yes | Lowercase identifier; must match folder name |
| `addon_name` | yes | Display name |
| `addon_description` | no | Short description |
| `category` | yes | `supplier`, `payment`, `notification`, `frontend`, or `tool` |
| `version` | yes | Addon semver string |
| `min_oshkelosh_version` | yes | Minimum host version (compare to `APP_VERSION`) |
| `max_oshkelosh_version` | no | Maximum supported host version |
| `python_requires` | no | PEP 440 specifier (default `>=3.11`) |

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

Install validates manifest fields, required files, version compatibility, and that `addon.py` defines exactly one concrete `BaseAddon` subclass matching the manifest.

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

Secrets are stored in `addon_configs.config` JSON. Admin forms should redact secrets on display (see Stripe/Printful routes).

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

Or call `persist_addon_config()` directly from JSON admin API: `PUT /api/v1/admin/addons/{addon_id}`.

## How core commerce uses addons

| Event | Service | Addon used |
|-------|---------|------------|
| Checkout | `POST /api/v1/orders/{id}/checkout` | First enabled `PaymentAddon` |
| Payment webhook | Addon route (e.g. Stripe) | Marks order `paid` |
| Order status → paid/shipped/delivered | `app/services/notifications.py` | First enabled `NotificationAddon` |
| Order status → paid (tagged products) | `app/services/fulfillment.py` | `SupplierAddon` per product tag |

You do **not** need to patch core routers if you hook through these flows or expose provider-specific routes.

## Admin UI options

1. **Dedicated admin routes** (recommended for complex config)  
   Return `get_admin_routes()` with Jinja templates under `templates/`.

2. **Generic JSON form**  
   Omit `get_admin_routes()`. Admins use `/admin/addons/{addon_id}/configure`.

3. **Enable/disable only**  
   List appears on `/admin/addons`; secrets live in `addon_configs` (admin UI or `PUT /api/v1/admin/addons/{addon_id}`), not in `.env`.

## Testing addons

```python
from app.addons.registry import AddonRegistry

registry = AddonRegistry()
registry.discover()
assert "my_addon" in [m["addon_id"] for m in registry.list_addons()]
```

Integration tests: enable addon via `persist_addon_config`, call routes with `httpx.AsyncClient`, mock external APIs.

See [`tests/test_addons.py`](../../tests/test_addons.py) and [`tests/test_addon_integration.py`](../../tests/test_addon_integration.py).

## OpenAPI

Addon HTTP routes are tagged `addons-{category}` in Swagger. See [docs/api/OPENAPI.md](../../docs/api/OPENAPI.md).

Export spec: `python scripts/export_openapi.py`

## Category-specific guides

- [Frontends / SPAs](frontends/README.md)
- [Payments](payments/README.md)
- [Suppliers](suppliers/README.md)
- [Notifications](notifications/README.md)

## Included reference addons

| ID | Category | Package |
|----|----------|---------|
| `default` | frontend | `frontends/default/` |
| `stripe` | payment | `payments/stripe/` |
| `printful` | supplier | `suppliers/printful/` |
| `email_postmark` | notification | `notifications/email/` |

Use these as copy-paste starting points.
