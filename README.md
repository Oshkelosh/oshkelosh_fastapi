# Oshkelosh

A **modular, extensible e-commerce framework** built from the ground up with FastAPI.

Every major facet (suppliers, payment processors, notifications, etc.) is a **self-contained, pluggable addon**. The public storefront is an interchangeable SPA, while the admin panel is server-rendered with Jinja2 templates.

## Documentation

Full developer guides live under **[`docs/`](docs/README.md)**:

| Topic | Guide |
|-------|--------|
| Documentation index | [`docs/README.md`](docs/README.md) |
| All plugins (overview) | [`app/addons/README.md`](app/addons/README.md) |
| Storefront / SPA development | [`app/addons/frontends/README.md`](app/addons/frontends/README.md) |
| Payment processors | [`app/addons/payments/README.md`](app/addons/payments/README.md) |
| Suppliers / fulfillment | [`app/addons/suppliers/README.md`](app/addons/suppliers/README.md) |
| Email / notifications | [`app/addons/notifications/README.md`](app/addons/notifications/README.md) |
| OpenAPI reference | [`docs/api/OPENAPI.md`](docs/api/OPENAPI.md) |
| API/admin surfaces | [`app/api/README.md`](app/api/README.md) |
| Security | [`docs/SECURITY.md`](docs/SECURITY.md) |

**API contract:** Swagger at `/docs`, or export a snapshot:

```bash
python scripts/export_openapi.py   # → docs/api/openapi.json
```

## Architecture

```
┌──────────────────────────────────────────────────┐
│                    Frontend                       │
│   Interchangeable SPA (React/Vue/Svelte/etc.)     │
│   Served from active frontend addon at /          │
└──────────────────────┬───────────────────────────┘
                       │ REST API (JSON)
┌──────────────────────▼───────────────────────────┐
│                 FastAPI App                       │
│                                                   │
│  /api/v1/*   → Public REST API (SPA consumed)     │
│  /admin/*    → Server-rendered admin (Jinja2)     │
│                                                   │
│  ┌───────────────────────────────────────────┐    │
│  │           Addon Registry                   │    │
│  │                                           │    │
│  │  ┌─────────────┐ ┌─────────────┐         │    │
│  │  │ Suppliers    │ │  Payments   │         │    │
│  │  │  Printful    │ │   Stripe    │         │    │
│  │  └─────────────┘ └─────────────┘         │    │
│  │  ┌─────────────┐ ┌─────────────┐         │    │
│  │  │ Notifications│ │   Future... │         │    │
│  │  │  Postmark    │ │             │         │    │
│  │  └─────────────┘ └─────────────┘         │    │
│  └───────────────────────────────────────────┘    │
└──────────────────────┬───────────────────────────┘
                       │
        ┌──────────────┼──────────────┐
        ▼              ▼              ▼
   Cloudflare D1   Cloudflare R2    External APIs
   (SQLite compat)   (Object store)  (Stripe, Printful)
```

Core commerce code **orchestrates** checkout, fulfillment, and catalog sync at fixed seams; each provider addon **implements** API clients, webhooks, tag rules, and admin UI. See [Core vs addon responsibilities](app/addons/README.md#core-vs-addon-responsibilities).

## Tech Stack

- **Framework**: FastAPI (ASGI)
- **Database**: Configurable — SQLite (local), D1 HTTP API (cloudflare_remote), or D1 Workers binding (stub)
- **Object Storage**: Configurable — local filesystem (local) or Cloudflare R2 (cloudflare_remote)
- **Templating**: Jinja2 (admin panel only)
- **Auth**: JWT (HS256) with access + refresh tokens
- **Validation**: Pydantic v2
- **ORM**: SQLModel (async)
- **Configuration**: Pydantic Settings
- **Logging**: Loguru

## Project Structure

```
oshkelosh/
├── app/
│   ├── main.py                  # FastAPI app factory + lifespan
│   ├── config.py                # Pydantic settings
│   ├── core/                    # Security, middleware, exceptions, deps
│   ├── db/                      # SQLite / D1 HTTP sessions
│   ├── storage/                 # Local filesystem / R2 backends
│   ├── models/                  # SQLModel domain models
│   ├── schemas/                 # Pydantic request/response schemas
│   ├── api/v1/                  # REST API routers
│   │   └── routers/             # auth, products, categories, cart, orders, r2, admin
│   ├── admin/                   # Jinja2 admin panel
│   │   ├── routes.py            # Admin route handlers
│   │   ├── templates/           # Jinja2 templates
│   │   └── static/              # Admin CSS
│   ├── addons/                  # Pluggable addon modules
│   │   ├── base.py              # Abstract base classes
│   │   ├── registry.py          # Auto-discovery + loading
│   │   ├── frontends/           # Storefront SPAs (default theme)
│   │   ├── suppliers/           # Supplier addons (Printful)
│   │   ├── payments/            # Payment addons (Stripe)
│   │   └── notifications/       # Notification addons (Postmark email)
│   ├── services/                # Shared business logic
│   └── utils/                   # Utility functions
├── docs/                        # Developer documentation index
├── app/addons/frontends/*/dist/ # Built storefront SPAs (per addon)
├── frontend/dist/               # Legacy SPA fallback (optional)
├── models/                      # SQLModel model definitions (top-level import)
├── schemas/                     # Pydantic schemas (top-level import)
├── tests/                       # Test suite
├── pyproject.toml               # Dependencies, tooling, and package metadata
├── .env.example                 # Environment variable template
└── README.md
```

## Quick Start

### 1. Clone and install

```bash
cd ~/programming/oshkelosh/oshkelosh_fastapi
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"   # runtime + dev deps from pyproject.toml
```

### 2. Configure

```bash
cp .env.example .env
# Edit .env with your actual values
```

At minimum, set `JWT_SECRET_KEY`. Use `DEPLOYMENT_PROFILE=local` (default) for SQLite + on-disk media with no Cloudflare account.

**Postmark, Printful, and Stripe** credentials are **not** `.env` variables — configure them in the admin panel after the server is running (see step 6 below).

**Local development (optional):** To work on addon packages without installing via the admin panel, clone each addon repo into its category path:

```bash
git clone git@github.com:Oshkelosh/stripe.git app/addons/payments/stripe
# …or any other Oshkelosh addon repo into the matching category path
```

Local clones are for development only and stay untracked by this repo (category `.gitignore` rules). Production installs addons through the admin panel.

### 3. Create the first admin

**Option A — Web setup (recommended):** Start the server (step 4), open `http://localhost:8000/` in your browser, and complete the setup wizard at `/setup`.

**Option B — CLI (headless / CI):**

```bash
python scripts/create_admin.py --email admin@example.com --password 'YourSecurePass123!'
```

### 4. Run the server

```bash
uvicorn app.main:app --reload --port 8000
# or: ./scripts/run_dev.sh
```

The API is available at `http://localhost:8000/api/v1/health`.

The admin panel is at `http://localhost:8000/admin` by default (`ADMIN_PREFIX` can change it).

The SPA static files are served at `http://localhost:8000/`.

### 5. Install and configure addons (admin)

Sign in at `/admin` with the account you created in step 3.

Install addon packages from **Dashboard → Install addon** (ZIP upload or HTTPS URL). Built-in addons (`manual` supplier, `sso` tool) ship with the host repo; everything else is installed this way. Installed packages require a **server restart** before they appear. By default, a restart flag is written to `data/restart.flag`; run `scripts/watch_addon_restart.py` alongside the server to restart automatically (see [Addon docs](app/addons/README.md)).

Then open the category tabs (Suppliers, Payments, **Notifications**, Frontends, Tools), enable each integration, and save its API keys.

| Integration | Admin URL |
|-------------|-----------|
| Stripe | `/admin/payments/stripe` |
| Printful | `/admin/suppliers/printful` |
| Postmark | `/admin/notifications/postmark` |
| Message templates | `/admin/notifications/messages` |

Settings are stored in the database (`addon_configs`), not in `.env`.

### Scheduled maintenance

Startup performs a one-time stale pending-order cleanup, but production should also call the admin JSON maintenance endpoints on a schedule:

```bash
curl -X POST \
  -H "Authorization: Bearer <admin-jwt>" \
  http://localhost:8000/api/v1/admin/jobs/pending-orders

curl -X POST \
  -H "Authorization: Bearer <admin-jwt>" \
  http://localhost:8000/api/v1/admin/jobs/abandoned-cart
```

### 6. Open API docs

- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`
- OpenAPI JSON: `http://localhost:8000/openapi.json` (or `python scripts/export_openapi.py`)

## Plugins and storefront

See **[`docs/README.md`](docs/README.md)** for the full documentation map.

- **New addon:** [`app/addons/README.md`](app/addons/README.md) — discovery, lifecycle, config, commerce hooks
- **New storefront:** [`app/addons/frontends/README.md`](app/addons/frontends/README.md) — SPA bootstrap, `GET /api/v1/storefront/config`, build layout
- **OpenAPI:** [`docs/api/OPENAPI.md`](docs/api/OPENAPI.md) — tags, schemas, checkout flow

## Deployment profiles

Backends are selected explicitly via `DEPLOYMENT_PROFILE` (or individual `DATABASE_BACKEND` / `STORAGE_BACKEND` vars). Copy [`.env.example`](.env.example) to `.env`.

| Profile | Database | Media storage | Use case |
|---------|----------|---------------|----------|
| `local` (default) | SQLite file | Local disk (`data/uploads`) | Development or a single VM without Cloudflare |
| `cloudflare_remote` | D1 HTTP API | R2 (S3 API) | FastAPI on a VPS with Cloudflare D1/R2 |
| `cloudflare_workers` | D1 binding (stub) | R2 binding (stub) | Future Workers Python runtime |

### Local (`DEPLOYMENT_PROFILE=local`)

```env
DEPLOYMENT_PROFILE=local
PUBLIC_APP_URL=http://localhost:8000
```

- SQLite database at `data/oshkelosh.db` (auto-created on startup).
- Uploaded images stored under `data/uploads` and served at `{PUBLIC_APP_URL}/media/files/...`.

### Cloudflare remote (`DEPLOYMENT_PROFILE=cloudflare_remote`)

```env
DEPLOYMENT_PROFILE=cloudflare_remote
D1_ACCOUNT_ID=your-account-id
D1_DATABASE_ID=your-database-uuid
D1_API_TOKEN=your-api-token
R2_ACCOUNT_ID=your-account-id
R2_ACCESS_KEY_ID=your-r2-access-key
R2_SECRET_ACCESS_KEY=your-r2-secret
R2_BUCKET_NAME=oshkelosh-media
```

- Database queries go to D1 via the [D1 HTTP API](https://developers.cloudflare.com/api/resources/d1/).
- Media uploads use the R2 S3-compatible API (`boto3`).
- Startup validates that all required credentials are present (no silent fallback).

### Cloudflare Workers (`DEPLOYMENT_PROFILE=cloudflare_workers`)

Not yet implemented. The app exposes `app.db.backends.d1_binding.set_d1_binding()` for a future Worker entrypoint that injects `env.DB`. Use `cloudflare_remote` until Workers support lands.

### Running migrations

```bash
# SQLite (local profile) — tables are created on startup; supplements run once:
python -c "from app.db.migrations import apply_migrations; apply_migrations()"

# D1 (tables also auto-created on startup for cloudflare_remote)
wrangler d1 execute <database-name> --file=migrations/d1/000_initial.sql
```

Check active backends: `GET /health` returns `database_backend` and `storage_backend`.

## Deployment

### VM + NGINX (recommended)

Run the app on a Linux VM with **systemd** (uvicorn) behind **NGINX** (TLS termination and reverse proxy). Use `DEPLOYMENT_PROFILE=local` for SQLite + disk media on the same machine, or `cloudflare_remote` if the VM talks to Cloudflare D1/R2.

#### 1. Install the app

```bash
sudo useradd --system --create-home --shell /usr/sbin/nologin oshkelosh
sudo mkdir -p /opt/oshkelosh
sudo chown oshkelosh:oshkelosh /opt/oshkelosh

# Switch to the service user (nologin account needs an explicit shell):
sudo -u oshkelosh -s /bin/bash

cd /opt/oshkelosh
git clone https://github.com/Oshkelosh/oshkelosh_fastapi.git .
python3 -m venv .venv
source .venv/bin/activate
pip install -e .

cp .env.example .env
# Generate secrets (32 hex chars each; run twice so they differ):
openssl rand -hex 16
# Edit .env — at minimum for production:
#   APP_ENV=production
#   DEBUG=false
#   JWT_SECRET_KEY=<output of openssl rand -hex 16>
#   ADMIN_SESSION_SECRET=<a different openssl rand -hex 16>
#   PUBLIC_APP_URL=https://shop.example.com
#   CORS_ORIGINS=https://shop.example.com
#   TRUSTED_PROXY_IPS=127.0.0.1   # so rate limits see the real client IP
# Plus D1/R2 vars if using cloudflare_remote
```

Or run a one-off command without an interactive shell: `sudo -u oshkelosh bash -c 'cd /opt/oshkelosh && …'`.

Ensure `data/` is writable by the service user (SQLite DB and/or local uploads, restart flag).

#### 2. systemd unit

Create a systemd unit so the app runs as the `oshkelosh` user on boot. Optionally add a second unit that restarts the app automatically after admin addon installs.

**App unit** — uvicorn listens on localhost only; NGINX (next step) is the public front.

`/etc/systemd/system/oshkelosh.service`:

```ini
[Unit]
Description=Oshkelosh FastAPI
After=network.target

[Service]
Type=simple
User=oshkelosh
Group=oshkelosh
WorkingDirectory=/opt/oshkelosh
EnvironmentFile=/opt/oshkelosh/.env
ExecStart=/opt/oshkelosh/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --proxy-headers --forwarded-allow-ips=127.0.0.1
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

**Addon restart (optional)** — After you install or update an addon in the admin UI, the app writes `data/restart.flag`. A small watcher polls that flag and runs a restart command. Skip this if you prefer to `systemctl restart oshkelosh` yourself after installs. See [`app/addons/README.md`](app/addons/README.md) for flag path / format overrides.

First create `/etc/sudoers.d/oshkelosh` (as root, preferably with `sudo visudo -f /etc/sudoers.d/oshkelosh`) so the service user can restart the app without a password:

```
oshkelosh ALL=NOPASSWD: /bin/systemctl restart oshkelosh
```

Then create `/etc/systemd/system/oshkelosh-restart-watcher.service`. Use `After=` only — do **not** use `Requires=` / `BindsTo=` / `PartOf=` on `oshkelosh.service`, or restarting the app will stop the watcher mid-cycle and can leave a stale flag that loops until start-limit.

```ini
[Unit]
Description=Oshkelosh addon restart watcher
After=oshkelosh.service

[Service]
Type=simple
User=oshkelosh
Group=oshkelosh
WorkingDirectory=/opt/oshkelosh
Environment="ADDON_INSTALL_RESTART_COMMAND=sudo systemctl restart oshkelosh"
ExecStart=/opt/oshkelosh/.venv/bin/python scripts/watch_addon_restart.py
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now oshkelosh
# Optional — skip if you restart manually after addon installs:
sudo systemctl enable --now oshkelosh-restart-watcher
```

#### 3. NGINX reverse proxy

`/etc/nginx/sites-available/oshkelosh`:

```nginx
server {
    listen 80;
    server_name shop.example.com;

    client_max_body_size 30m;  # addon ZIP uploads (default allow 25 MB)

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Connection "";
        proxy_read_timeout 60s;
    }
}
```

```bash
sudo ln -s /etc/nginx/sites-available/oshkelosh /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

Point the domain’s DNS **A** (or **AAAA**) record at this server’s public IP before requesting a certificate. Certbot’s HTTP challenge will fail if the name does not resolve here yet.

```bash
sudo certbot --nginx -d shop.example.com   # TLS via Let's Encrypt
```

Certbot rewrites the NGINX site for HTTPS. Use `https://shop.example.com` afterward — plain HTTP will redirect or fail depending on the config.

If your DNS provider also **proxies** traffic (for example Cloudflare’s orange-cloud proxy), set that provider’s SSL/TLS mode so the hop from the proxy to this server is encrypted (**Full** or **Full (strict)**). With **Flexible** / HTTP-only to origin, browsers often cannot load the site after certbot enables HTTPS on NGINX.

After TLS is enabled, keep `PUBLIC_APP_URL` and `CORS_ORIGINS` on `https://…`.

#### 4. Go live

1. Open `https://shop.example.com/setup` and create the first admin (or use `scripts/create_admin.py`).
2. Sign in at `/admin`. Addons such as the storefront are **not** shipped by default — install them from **Dashboard → Install addon** (ZIP upload or HTTPS URL to a ZIP). For the reference storefront, use the GitHub source archive (includes `oshkelosh-addon.json` and a prebuilt `dist/`):
   `https://github.com/Oshkelosh/default_frontend/archive/refs/heads/main.zip`
   After install, restart the server (or rely on the addon-restart watcher), then enable and configure each addon under **Addons** (Stripe / Printful / Postmark, storefront, etc.).
3. Schedule maintenance jobs (cron or similar) against the admin JSON endpoints — see [Scheduled maintenance](#scheduled-maintenance) above.

See [`docs/SECURITY.md`](docs/SECURITY.md) for production secrets, CORS, and proxy IP trust.

## Testing

```bash
pytest
pytest --confcutdir=tests/isolated tests/isolated/   # storage tests without full app import
pytest --cov=app
pytest --cov=app --cov-report=html
```

## License

MIT
