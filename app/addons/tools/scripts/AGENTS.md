# Scripts (`scripts`) — AGENTS

## Role

Built-in tool for injecting external storefront `<script>` tags (analytics, chat widgets, and similar). Addon ID: `scripts`.

## File map

- `README.md`
- `__init__.py`
- `addon.py`
- `config.py`
- `oshkelosh-addon.json`
- `parse.py`
- `routes.py`
- `templates/`
- `tests/`

## Package specifics

**Category ceiling:** Many tools may be active; honor dual enable flags where the README documents them.
- Exposes storefront scripts via `list_storefront_scripts()` → storefront config

## Invariants

- Implement the matching category ABC; do not patch host `app/services/*.py` with provider branches
- Credentials and enable flags live in `addon_configs` (admin UI), not host `.env`
- Use `app/addons/log.py` for structured logging
- Admin mutating forms need CSRF; use `render_addon_admin_page` correctly (do not pass `flash` via `**_common_ctx`)
- Webhook parse paths must not write the DB — core owns idempotency
- Nested `.git` (if present): this package is its own repo; the host gitignores this directory

## Prefer / Avoid

- Prefer: extend this package and the category ABC; keep provider API clients here
- Avoid: editing host `app/services/` for this provider; putting secrets in host `.env`

## See also

- [README.md](README.md) — package how-to
- [../README.md](../README.md) — category guide
- [../../AGENTS.md](../../AGENTS.md) — host addon boundary
- [../../README.md](../../README.md) — plugin development
- [../../../../AGENTS.md](../../../../AGENTS.md), [../../../../DESIGN.md](../../../../DESIGN.md)
