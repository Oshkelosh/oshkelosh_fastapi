#!/usr/bin/env bash
# Start uvicorn for local development and write its PID for the restart watcher.
#
# Terminal 1:
#   ./scripts/run_dev.sh
#
# Terminal 2 (restart after addon install):
#   ADDON_INSTALL_RESTART_COMMAND='kill -HUP $(cat .oshkelosh.pid)' \\
#     python scripts/watch_addon_restart.py

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PID_FILE="$ROOT/.oshkelosh.pid"

cleanup() {
  rm -f "$PID_FILE"
}
trap cleanup EXIT INT TERM

echo "$$" > "$PID_FILE"
echo "Wrote PID $$ to .oshkelosh.pid"
echo "In another terminal, run:"
echo "  ADDON_INSTALL_RESTART_COMMAND='kill -HUP \$(cat .oshkelosh.pid)' python scripts/watch_addon_restart.py"
echo ""

exec uvicorn app.main:app --reload --port 8000
