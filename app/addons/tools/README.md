# Tools addons

Optional advanced capabilities for a shop: analytics, A/B testing, heatmaps, SEO helpers, SSO, and similar integrations.

**Roadmap:** [Tool_List.md](Tool_List.md) — optional third-party integrations, priorities, and **Core prerequisites** for tool authors.

## Conventions

| Surface | Path pattern | Example |
|---------|--------------|---------|
| API | `/api/v1/tools/{addon_id}/...` | `/api/v1/tools/{addon_id}/...` |
| Admin | `/admin/tools/{addon_id}/...` | `/admin/tools/{addon_id}` |
| Admin list | `/admin/tools` | Enable and open each tool |

Multiple tools may be enabled at once (unlike payment or frontend addons).

## Storefront integration

Override `list_public_providers()` on your `ToolAddon` subclass to expose public auth metadata. Core reads this via [`app/services/sso_discovery.py`](../../services/sso_discovery.py) and includes it in `GET /api/v1/storefront/config` under `auth.sso_providers`.

Override `list_storefront_scripts()` to publish external script descriptors. Core aggregates them via [`app/services/tool_discovery.py`](../../services/tool_discovery.py) into `tools.scripts` on the same storefront config endpoint. The default frontend injects matching tags into `<head>` (see the built-in [`scripts`](scripts/README.md) tool).

## Creating a tool addon

1. Add `app/addons/tools/<name>/` with `__init__.py`, `addon.py`, and `README.md`.
2. Subclass `ToolAddon` from `app.addons.tools.base`.
3. Set `addon_id`, `addon_name`, `addon_description`, and `version`.
4. Implement `config_schema()`, `initialize()`, and `shutdown()`.
5. Optionally add `routes.py` for API/admin routers and Jinja templates under `templates/`.
6. Enable and configure at **Admin → Tools**.

See [../README.md](../README.md) for the full addon checklist.

## Installed tool addons

| Addon ID | README |
|----------|--------|
| `sso` | [sso/README.md](sso/README.md) |
| `scripts` | [scripts/README.md](scripts/README.md) |
