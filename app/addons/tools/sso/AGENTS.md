# SSO Login (`sso`) — AGENTS

## Role

Built-in social sign-in for the storefront via Google, Facebook, or custom OpenID Connect providers. Addon ID: `sso`.

## File map

- `README.md`
- `__init__.py`
- `addon.py`
- `config.py`
- `oshkelosh-addon.json`
- `providers/`
- `routes.py`
- `service.py`
- `templates/`
- `tests/`
- `validation.py`

## Package specifics

**Category ceiling:** Many tools may be active; honor dual enable flags where the README documents them.
**Config fields:** `is_active` (bool), `google.enabled` (bool), `google.client_id` (string), `google.client_secret` (secret), `facebook.enabled` (bool), `facebook.app_id` (string), `facebook.app_secret` (secret), `oidc_providers[]` (list), `oidc_providers[].provider_id` (string), `oidc_providers[].display_name` (string), `oidc_providers[].enabled` (bool), `oidc_providers[].issuer_url` (string)
- Dual enable: addon enabled in Admin → Addons **and** config `is_active`

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
