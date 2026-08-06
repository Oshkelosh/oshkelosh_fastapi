# DB — AGENTS

## Role

Database session backends (SQLite, D1 HTTP) and the startup migration runner hook. Selected via `DATABASE_BACKEND` or `DEPLOYMENT_PROFILE`.

## File map

| Path | Notes |
|------|--------|
| Session / engine modules | sqlite vs `d1_http` |
| Migration apply hook | runs `migrations/d1/*.sql` at startup |
| [README.md](README.md) | local detail |

## Invariants

- Only supported backends today: `sqlite` and `d1_http` (Workers binding is DESIGN Planned — not implemented)
- No Alembic
- D1 HTTP: writes queue until flush; `rollback()` clears the local queue only
- After raw SQL updates (e.g. inventory), `session.refresh()` so the identity map matches
- No implicit relationship lazy loads

## Prefer / Avoid

- Prefer: explicit `select` / commerce loaders; idempotent SQL migrations for existing DBs
- Avoid: assuming ORM `create_all` alone upgrades existing databases

## See also

- [README.md](README.md)
- [../../docs/DATABASE.md](../../docs/DATABASE.md)
- [../../migrations/AGENTS.md](../../migrations/AGENTS.md)
