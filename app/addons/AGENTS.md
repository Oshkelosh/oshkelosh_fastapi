# Addons — AGENTS

## Role

Pluggable extension surface: discovery (`registry.py`), route mounting (`mount.py`), category ABCs, ZIP/URL install boundary. Core stays light; packages under `<category>/<name>/` implement providers.

## File map

| Path | Notes |
|------|--------|
| `base.py`, `registry.py`, `mount.py`, `log.py` | Host addon infrastructure |
| `frontends/`, `payments/`, `suppliers/`, `notifications/`, `tools/` | Categories + ABCs + packages |
| `*/README.md` | Category how-to |
| `<category>/<name>/AGENTS.md` | Per-package agent contract |

## Invariants

- Core orchestrates; addons implement — extend ABCs, do not add provider branches in `app/services/*.py`
- Logging via `app/addons/log.py`, not raw loguru in packages
- `render_addon_admin_page` — do not pass `flash` through `**_common_ctx`
- Built-ins tracked by host: `suppliers/manual`, `tools/sso`, `tools/scripts`; other packages are gitignored clones or ZIP installs
- Each package should carry its own `AGENTS.md`
- Frontend: only one active. Payment / notification: one active recommended (notification: per channel)

## Prefer / Avoid

- Prefer: admin ZIP/URL install in production; separate addon git repos for non-built-ins
- Avoid: Git submodules; editing host services for provider-specific clients

## See also

- [README.md](README.md) — full plugin guide
- [../../AGENTS.md](../../AGENTS.md), [../../DESIGN.md](../../DESIGN.md)
