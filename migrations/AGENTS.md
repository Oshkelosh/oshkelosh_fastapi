# Migrations — AGENTS

## Role

Supplemental DDL (indexes, constraints, awkward tables) applied at startup for **all** SQL backends. Application tables come from SQLModel `create_all` on fresh installs.

## File map

```
migrations/d1/
├── 000_….sql
└── NNN_description.sql   # lexicographic order; zero-padded prefix
```

Folder name `d1/` is historical — the same files run for SQLite and D1 HTTP.

## Invariants

- Idempotent SQL only: `IF NOT EXISTS`, `INSERT OR IGNORE`, repair-safe re-adds
- Zero-padded numeric filename prefixes for stable order
- Destructive DDL (drops, renames, type changes) is **not** supported by the runner — needs a manual plan
- Tracker table `schema_migrations` records applied filenames; re-running startup is safe

## Prefer / Avoid

- Prefer: additive `ALTER TABLE … ADD COLUMN` / `CREATE INDEX IF NOT EXISTS`
- Avoid: Alembic; assuming the runner can ship breaking renames

## See also

- [README.md](README.md)
- [../docs/DATABASE.md](../docs/DATABASE.md)
- [../app/db/AGENTS.md](../app/db/AGENTS.md)
