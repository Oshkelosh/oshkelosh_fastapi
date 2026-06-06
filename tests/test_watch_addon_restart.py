"""Tests for scripts/watch_addon_restart.py."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parent.parent
WATCHER = REPO_ROOT / "scripts" / "watch_addon_restart.py"


def _load_watcher():
    spec = importlib.util.spec_from_file_location("watch_addon_restart", WATCHER)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_exits_when_restart_command_unset(tmp_path: Path):
    flag = tmp_path / "restart.flag"
    result = subprocess.run(
        [
            sys.executable,
            str(WATCHER),
            "--flag-file",
            str(flag),
            "--poll-interval",
            "0.1",
        ],
        cwd=REPO_ROOT,
        env={"ADDON_INSTALL_RESTART_COMMAND": ""},
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert result.returncode == 1
    assert "ADDON_INSTALL_RESTART_COMMAND" in result.stderr


def test_restarts_and_removes_flag(tmp_path: Path):
    flag = tmp_path / "restart.flag"
    flag.write_text('{"reason": "addon_installed"}\n', encoding="utf-8")
    ran: list[str] = []

    def fake_run(command, **kwargs):
        ran.append(command)

        class Result:
            returncode = 0
            stdout = ""
            stderr = ""

        return Result()

    watcher = _load_watcher()
    with patch("subprocess.run", side_effect=fake_run):
        watcher._handle_flag(flag, "echo restarted")

    assert ran == ["echo restarted"]
    assert not flag.exists()
