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

**Postmark, Printful, and Stripe** credentials are **not** `.env` variables — configure them in the admin panel after the server is running (see step 5 below).

### 3. Create the first admin

**Option A — Web setup (recommended):** Start the server (step 4), open `http://localhost:8000/` in your browser, and complete the setup wizard at `/setup`.

**Option B — CLI (headless / CI):**

```bash
python scripts/create_admin.py --email admin@example.com --password 'YourSecurePass123!'
```

Or set `ADMIN_EMAIL` and `ADMIN_PASSWORD` in `.env` and run `python scripts/create_admin.py` with no arguments.

### 4. Run the server

```bash
uvicorn app.main:app --reload --port 8000
```

The API is available at `http://localhost:8000/api/v1/health`.

The admin panel is at `http://localhost:8000/admin`. 

The SPA static files are served at `http://localhost:8000/`.

### 5. Log in and configure integrations

Sign in at `/admin` with the account you created in step 3.

### 6. Configure integrations (admin)

Log in at `/admin`, open the category tabs (Suppliers, Payments, Frontends, Tools), enable each integration, then save its API keys.

You can also install third-party addons from **Dashboard → Install addon** (ZIP or HTTPS URL). Installed packages require a **server restart** before they appear. By default, a restart flag is written to `data/restart.flag`; run `scripts/watch_addon_restart.py` alongside the server to restart automatically (see [Addon docs](app/addons/README.md)).

| Integration | Admin URL |
|-------------|-----------|
| Stripe | `/admin/payments/stripe` |
| Printful | `/admin/suppliers/printful` |
| Email (Postmark) | `/admin/notifications/email` |

Settings are stored in the database (`addon_configs`), not in `.env`.

### 7. Open API docs

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
| `local` (default) | SQLite file | Local disk (`data/uploads`) | Development, Docker without Cloudflare |
| `cloudflare_remote` | D1 HTTP API | R2 (S3 API) | FastAPI on VPS/Docker/Railway |
| `cloudflare_workers` | D1 binding (stub) | R2 binding (stub) | Future Workers Python runtime |

### Local (`DEPLOYMENT_PROFILE=local`)

```env
DEPLOYMENT_PROFILE=local
D1_LOCAL_DB_PATH=data/oshkelosh.db
LOCAL_MEDIA_DIR=data/uploads
LOCAL_MEDIA_BASE_URL=http://localhost:8000/media/files
```

- SQLite database at `data/oshkelosh.db` (auto-created on startup).
- Uploaded images stored under `LOCAL_MEDIA_DIR` and served at `/media/files/...`.

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
# SQLite (local profile)
python -c "from app.db.base import auto_create_tables; auto_create_tables()"

# D1 (tables also auto-created on startup for cloudflare_remote)
wrangler d1 execute <database-name> --file=migrations/001_init.sql
```

Check active backends: `GET /health` returns `database_backend` and `storage_backend`.

## Deployment

### Cloudflare Pages (Recommended)

1. Push your code to Git
2. Connect the repo to Cloudflare Pages
3. Build settings:
   - Framework preset: None
   - Build command: `echo "No build step - app serves static files directly"`
   - Build output directory: `frontend/dist`
4. Add environment variables in the Cloudflare dashboard
5. Deploy

### Cloudflare Workers

Use `wrangler.toml` to configure Workers deployment:

```toml
name = "oshkelosh"
type = "python"
workers_dev = true

[vars]
DEBUG = true
```

### Docker

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY pyproject.toml README.md ./
COPY app/ app/
COPY models/ models/
COPY schemas/ schemas/
RUN pip install --no-cache-dir .
COPY . .
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

```bash
docker build -t oshkelosh .
docker run -p 8000:8000 --env-file .env oshkelosh
```

## Testing

```bash
pytest
pytest --confcutdir=tests/isolated tests/isolated/   # storage tests without full app import
pytest --cov=app
pytest --cov=app --cov-report=html
```

## License

MIT
