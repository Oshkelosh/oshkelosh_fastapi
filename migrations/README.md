# SQL migrations

Supplemental DDL for indexes, constraints, and tables that are awkward to express in SQLModel. Application tables are created separately — see below.

## Layout

```
migrations/
└── d1/
    ├── 000_initial.sql
    └── NNN_description.sql   # future files
```

Files are sorted **lexicographically by filename**. Use a zero-padded numeric prefix (`000`, `001`, …) so order is stable.

## When SQL vs ORM

| Concern | Mechanism |
|---------|-----------|
| Application tables (`users`, `orders`, `products`, `product_variants`, …) | SQLModel bootstrap / `create_all` on fresh installs ([`app/db/base.py`](../app/db/base.py)) |
| Indexes, partial unique constraints, supplemental tables | `migrations/d1/*.sql`, applied at startup and by bootstrap scripts |

There is no Alembic-style model diff runner. Changing a SQLModel field updates `create_all` on fresh installs only; existing databases still need a deliberate SQL migration if you cannot recreate them.

Write migration SQL as **idempotent**: `CREATE TABLE IF NOT EXISTS`, `CREATE INDEX IF NOT EXISTS`, `INSERT OR IGNORE`. The runner skips duplicate-column errors on SQLite.

## Idempotency and tracking

[`app/db/migrations.py`](../app/db/migrations.py) applies pending files at **application startup** (and from CLI scripts such as `create_admin.py`):

1. Ensure `schema_migrations` tracker table exists.
2. Load applied filenames from the tracker.
3. Run each new `.sql` file statement-by-statement.
4. Record the filename in `schema_migrations`.

Re-running startup or the migration helper is safe — already-applied files are skipped.

## D1 vs SQLite

The same `migrations/d1/` directory is used for all SQL backends:

| Backend | How migrations run |
|---------|-------------------|
| `sqlite` | Direct `sqlite3` connection to `data/oshkelosh.db` |
| `d1_http` | `D1Connection.execute()` per statement |
| `d1_binding` | `D1BindingConnection.execute()` per statement |

The folder name reflects the original D1/wrangler target; local SQLite dev uses the same files.

## Related docs

- [Database backends](../docs/DATABASE.md)
- [Security — schema notes](../docs/SECURITY.md#schema-and-migrations)
