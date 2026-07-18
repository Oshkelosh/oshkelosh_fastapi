#!/usr/bin/env python3
"""Watch for addon install restart flags and restart the server.

Run from the repository root alongside the app process:

    ADDON_INSTALL_RESTART_COMMAND="systemctl restart oshkelosh" \\
      python scripts/watch_addon_restart.py

Local dev (uvicorn started via scripts/run_dev.sh):

    ADDON_INSTALL_RESTART_COMMAND='kill -HUP $(cat .oshkelosh.pid)' \\
      python scripts/watch_addon_restart.py
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_FLAG_FILE = "data/restart.flag"
DEFAULT_POLL_INTERVAL = 2.0


def _resolve_flag_path(args: argparse.Namespace) -> Path:
    raw = args.flag_file or os.environ.get("ADDON_INSTALL_RESTART_FLAG_FILE", DEFAULT_FLAG_FILE)
    if not raw.strip():
        print("Restart flag path is empty; nothing to watch.", file=sys.stderr)
        raise SystemExit(1)
    path = Path(raw)
    if not path.is_absolute():
        path = REPO_ROOT / path
    return path


def _resolve_restart_command() -> str:
    command = os.environ.get("ADDON_INSTALL_RESTART_COMMAND", "").strip()
    if not command:
        print(
            "ADDON_INSTALL_RESTART_COMMAND is not set.\n"
            "Example: ADDON_INSTALL_RESTART_COMMAND='systemctl restart oshkelosh'",
            file=sys.stderr,
        )
        raise SystemExit(1)
    return command


def _run_restart(command: str) -> bool:
    print(f"Running restart command: {command}")
    # shell=True is intentional: the command comes from the operator's own
    # ADDON_INSTALL_RESTART_COMMAND env var (trusted, same privilege level)
    # and legitimately uses shell features like `$(cat .oshkelosh.pid)`.
    # Never feed this from request/user data.
    result = subprocess.run(
        command,
        shell=True,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    if result.stdout:
        print(result.stdout, end="" if result.stdout.endswith("\n") else "\n")
    if result.stderr:
        print(result.stderr, end="" if result.stderr.endswith("\n") else "\n", file=sys.stderr)
    if result.returncode != 0:
        print(f"Restart command failed with exit code {result.returncode}", file=sys.stderr)
        return False
    return True


def _handle_flag(flag_path: Path, restart_command: str) -> None:
    try:
        payload = flag_path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        print(f"Could not read flag file {flag_path}: {exc}", file=sys.stderr)
        return

    if payload:
        print(f"Restart flag detected at {flag_path}")
        print(payload)

    # Consume the flag before restarting so an interrupted restart cannot loop.
    try:
        flag_path.unlink(missing_ok=True)
        print(f"Removed flag file {flag_path}")
    except OSError as exc:
        print(f"Warning: could not remove flag file {flag_path}: {exc}", file=sys.stderr)
        return

    _run_restart(restart_command)


def watch(flag_path: Path, restart_command: str, poll_interval: float) -> None:
    print(f"Watching {flag_path} (poll every {poll_interval}s)")
    last_mtime: float | None = None
    restarting = False

    while True:
        try:
            if flag_path.exists():
                mtime = flag_path.stat().st_mtime
                if last_mtime != mtime and not restarting:
                    restarting = True
                    try:
                        _handle_flag(flag_path, restart_command)
                    finally:
                        restarting = False
                        last_mtime = flag_path.stat().st_mtime if flag_path.exists() else None
                else:
                    last_mtime = mtime
            else:
                last_mtime = None
        except KeyboardInterrupt:
            print("\nStopped.")
            raise SystemExit(0)

        time.sleep(poll_interval)


def main() -> int:
    parser = argparse.ArgumentParser(description="Watch addon install restart flag and restart the server.")
    parser.add_argument(
        "--flag-file",
        default=None,
        help=f"Path to restart flag (default: {DEFAULT_FLAG_FILE} or ADDON_INSTALL_RESTART_FLAG_FILE)",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=DEFAULT_POLL_INTERVAL,
        help=f"Seconds between checks (default: {DEFAULT_POLL_INTERVAL})",
    )
    args = parser.parse_args()

    flag_path = _resolve_flag_path(args)
    restart_command = _resolve_restart_command()
    watch(flag_path, restart_command, args.poll_interval)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
