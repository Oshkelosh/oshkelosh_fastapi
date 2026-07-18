# app/db — database layer

Backend-agnostic session/connection plumbing. Services and routes depend on
`get_session` / `session_scope` and never on a specific backend.

| File | Role |
|------|------|
| `connection.py` | Engine/session factory; `get_session` dependency, `session_scope` context manager, `mark_instance_dirty` |
| `base.py` | `ModelBase` (id + timestamps) and `utc_now` |
| `migrations.py` | Startup runner for `migrations/d1/*.sql`; tracks applied files in `schema_migrations` |
| `d1_client.py` | Cloudflare D1 HTTP API client (query/execute/batch) |
| `sqlite_utils.py` | Local SQLite helpers |
| `backends/d1_http_session.py` | Async session adapter over the D1 HTTP API (see its module docstring for transaction semantics) |

Backends: `sqlite` (local file) and `d1_http` (Cloudflare D1 over HTTP),
selected by `DATABASE_BACKEND` / `DEPLOYMENT_PROFILE`. Details and ORM
conventions: [docs/DATABASE.md](../../docs/DATABASE.md).

Key constraint carried by both backends: no lazy relationship loading — use the
explicit loaders in `app/services/commerce.py` or `select(...)` queries.
