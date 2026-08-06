# Models — AGENTS

## Role

SQLModel table definitions. Import path is top-level `from models...` (not under `app/`).

## File map

One table per file; all inherit `ModelBase`. Package `__init__.py` must import new models so `SQLModel.metadata.create_all` sees them. See [README.md](README.md).

## Invariants

- Register every new model in `models/__init__.py`
- Money fields are integer cents
- Cart and orders reference `variant_id`; supplier linkage lives on `ProductVariant`
- Fresh installs get tables from SQLModel bootstrap; existing DBs need paired `migrations/d1/` SQL for additive changes

## Prefer / Avoid

- Prefer: pairing model field adds with an idempotent migration file
- Avoid: relying on `create_all` to migrate production/D1 data

## See also

- [README.md](README.md)
- [../migrations/AGENTS.md](../migrations/AGENTS.md)
- [../docs/DATABASE.md](../docs/DATABASE.md)
