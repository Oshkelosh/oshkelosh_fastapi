# Oshkelosh — AGENTS

Ops contract for agents working in this repository. How-to detail lives in READMEs; this file is ceilings and traps.

**DESIGN contract:** [DESIGN.md](DESIGN.md). **Planned is not implemented** — do not build toward unshipped DESIGN from coding context.

## How to run & test

```bash
pip install -e ".[dev]"
cp .env.example .env   # set JWT_SECRET_KEY at minimum
uvicorn app.main:app --reload --port 8000
# or: ./scripts/run_dev.sh
```

- First admin: `/setup` wizard or `python scripts/create_admin.py`
- Tests: `pytest`; isolated: `pytest --confcutdir=tests/isolated tests/isolated/`
- Lint/type: ruff, mypy, pre-commit (see `pyproject.toml`)
- OpenAPI snapshot: `python scripts/export_openapi.py`
- Addon restart watcher (dev): `python scripts/watch_addon_restart.py`

Provider credentials (Stripe, Printify, Postmark, …) are **not** `.env` — configure in admin (`addon_configs`).

## Principles

- **Core orchestrates; addons implement** — no provider `if` branches in `app/services/*.py`; extend category ABCs ([app/addons/README.md](app/addons/README.md#core-vs-addon-responsibilities))
- **Addon packages are separate repos** — host gitignores `app/addons/<category>/*/` except built-ins (`manual`, `sso`, `scripts`); no Git submodules; prod install = admin ZIP/URL
- **Config layers** — host/backends/JWT/CORS in `.env`; site branding/tax/shipping in `site_settings`; provider secrets in `addon_configs`
- **Product + variant** — cart/orders use `variant_id`; supplier IDs live on variants
- **Money** — integer cents
- **Webhooks** — core owns idempotency; addon parse must not write DB
- **Schema** — SQLModel `create_all` on fresh install; existing DBs get idempotent `migrations/d1/*.sql` (no Alembic)
- **Async ORM** — no lazy loads; explicit loaders in `app/services/commerce.py`

## Architecture map

```
oshkelosh_fastapi/
├── AGENTS.md, DESIGN.md, README.md
├── app/
│   ├── main.py, config.py, openapi.py
│   ├── core/          # security, middleware, deps, rate limit
│   ├── db/            # sqlite + d1_http sessions, migration runner
│   ├── storage/       # local / R2
│   ├── api/v1/        # REST routers
│   ├── admin/         # Jinja admin
│   ├── setup/         # first-run wizard
│   ├── storefront/    # SEO injection, SPA hooks
│   ├── services/      # orchestration seams + utilities
│   └── addons/        # registry, mount, category ABCs + packages
│       └── <category>/<addon_id>/   # built-ins or nested-git clones
├── models/            # SQLModel tables (import path)
├── schemas/           # Pydantic API schemas
├── migrations/d1/     # supplemental SQL (all backends)
├── scripts/, tests/, docs/
└── data/              # runtime DB, uploads, restart.flag
```

## Gotchas

- Production rejects default `JWT_SECRET_KEY`; requires distinct ≥32-char `ADMIN_SESSION_SECRET`
- `DEPLOYMENT_PROFILE=local|cloudflare_remote` overrides individual backends
- Behind a proxy: set `TRUSTED_PROXY_IPS` or rate limits key on the wrong IP
- `PUBLIC_APP_URL` / `CORS_ORIGINS` must match the real public URL (SSO, media, email links)
- D1 HTTP: writes queue until flush; `rollback()` is local queue only; refresh after raw SQL
- Folder `migrations/d1/` is historical — same SQL applies to SQLite and D1
- Addon install needs a full restart (flag file + watcher); app does not self-restart
- Nested addon `.git`: `git status` inside the package is the **addon** repo; host ignores those dirs
- Admin mutating forms need CSRF; `render_addon_admin_page` — do not pass `flash` via `**_common_ctx`
- `GET /api/v1/media/{key}` requires admin auth
- Maintenance jobs are scheduled externally (see DESIGN Planned)

## Child AGENTS.md index

| Path | Role |
|------|------|
| [app/addons/AGENTS.md](app/addons/AGENTS.md) | Discovery, mount, extension boundary |
| [app/addons/suppliers/AGENTS.md](app/addons/suppliers/AGENTS.md) | Supplier category catalog/fulfillment contract |
| [app/services/AGENTS.md](app/services/AGENTS.md) | Seams vs utilities |
| [app/db/AGENTS.md](app/db/AGENTS.md) | Backend sessions, migrations hook |
| [models/AGENTS.md](models/AGENTS.md) | SQLModel tables |
| [migrations/AGENTS.md](migrations/AGENTS.md) | Idempotent supplemental SQL |

**Installed addon packages** each carry their own `AGENTS.md` under `app/addons/<category>/<name>/` (frontends, payments, suppliers, notifications, tools). Nested-git clones own that file in the addon repo, not the host index.
