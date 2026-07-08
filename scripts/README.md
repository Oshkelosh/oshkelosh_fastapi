# Scripts

Utility scripts for local development, deployment, and maintenance. Run from the repository root unless noted.

| Script | Purpose |
|--------|---------|
| [`run_dev.sh`](run_dev.sh) | Start uvicorn for local dev; writes PID to `.oshkelosh.pid` for the restart watcher |
| [`create_admin.py`](create_admin.py) | Create the first admin user interactively (one-shot CLI) |
| [`watch_addon_restart.py`](watch_addon_restart.py) | Poll `data/restart.flag` and run `ADDON_INSTALL_RESTART_COMMAND` after addon install |
| [`export_openapi.py`](export_openapi.py) | Export OpenAPI schema to `docs/api/openapi.json` |

## Common invocations

```bash
./scripts/run_dev.sh
python scripts/create_admin.py
python scripts/export_openapi.py
ADDON_INSTALL_RESTART_COMMAND='kill -HUP $(cat .oshkelosh.pid)' python scripts/watch_addon_restart.py
```

See [app/addons/README.md](../app/addons/README.md) for addon install and restart-flag details.
