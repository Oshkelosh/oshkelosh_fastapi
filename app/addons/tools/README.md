# Tools addons

Optional advanced capabilities for a shop: analytics, A/B testing, heatmaps, SEO helpers, and similar integrations.

## Conventions

| Surface | Path pattern | Example |
|---------|--------------|---------|
| API | `/api/v1/tools/{addon_id}/...` | `/api/v1/tools/plausible/events` |
| Admin | `/admin/tools/{addon_id}/...` | `/admin/tools/plausible` |
| Admin list | `/admin/tools` | Enable and open each tool |

Multiple tools may be enabled at once (unlike payment or frontend addons).

## Creating a tool addon

1. Add `app/addons/tools/<name>/` with `__init__.py` and `addon.py`.
2. Subclass `ToolAddon` from `app.addons.tools.base`.
3. Set `addon_id`, `addon_name`, `addon_description`, and `version`.
4. Implement `config_schema()`, `initialize()`, and `shutdown()`.
5. Optionally add `routes.py` for API/admin routers and Jinja templates under `templates/`.
6. Enable and configure at **Admin → Tools**.

See [../README.md](../README.md) for the full addon checklist.
