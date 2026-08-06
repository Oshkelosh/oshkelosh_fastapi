# Oshkelosh — DESIGN

Product design contract for the Oshkelosh modular e-commerce host.

**Agents:** anything under **Planned** is not implemented. Do not build toward Planned items from coding context. See [AGENTS.md](AGENTS.md).

## Vision

Oshkelosh is a modular FastAPI e-commerce host: **core orchestrates** commerce lifecycle; **addons implement** providers. The public storefront is an interchangeable SPA served from the active frontend addon. The admin panel is server-rendered Jinja2. REST lives under `/api/v1/*`.

## Goals (shipped)

- Product + variant catalog; cart and orders reference `variant_id`
- Checkout with tax/shipping seams; order status transitions and fulfillment on `paid`
- Pluggable addon categories: suppliers, payments, notifications, tools, frontends
- Database backends: SQLite (local) and Cloudflare D1 HTTP (`d1_http`)
- Object storage: local filesystem and Cloudflare R2
- Admin ZIP/URL addon install into `app/addons/<category>/<id>/`
- Dual auth: API Bearer JWT (no CSRF); admin cookie session + CSRF (admin JSON jobs use JWT)
- Webhook idempotency owned by core; addon `parse_webhook()` must not write the DB
- Provider credentials in `addon_configs`; host/backends/JWT/CORS in `.env`
- Site branding / tax / shipping in `site_settings`; frontend-specific options in addon config

## Planned (not implemented)

- **D1 Workers binding** — README may still mention it; only `sqlite` and `d1_http` are supported backends today ([docs/DATABASE.md](docs/DATABASE.md))
- **In-process recurring maintenance** — production should schedule `POST /api/v1/admin/jobs/abandoned-cart` and `…/pending-orders`; startup pending-order cleanup is defense-in-depth only

## Success criteria

- Adding a supplier, payment processor, notification channel, tool, or frontend does **not** require provider-name branches in `app/services/*.py` — extend the category ABC and ship a package
- Fresh install follows the root README path (`pip install -e ".[dev]"`, `.env`, setup wizard or `create_admin.py`, uvicorn)
- Schema evolution for existing DBs is additive, idempotent SQL under `migrations/d1/`
- Only one frontend addon is active at a time
- Provider secrets stay out of `.env`

## Non-goals / ceilings

- No Git submodules for addon packages (separate repos; host gitignores category `*/` except built-ins)
- No Alembic-style model diff runner
- No provider-specific API clients or webhook DB writes in core services
- No in-app self-restart after addon install (restart flag + external watcher / process manager)
- Recurring maintenance is not assumed fully in-process
- Workers D1 binding is not a supported deployment path until Planned ships

## See also

- [AGENTS.md](AGENTS.md) — ops contract for agents
- [app/addons/README.md](app/addons/README.md) — extension model and seams
- [docs/README.md](docs/README.md) — documentation index
