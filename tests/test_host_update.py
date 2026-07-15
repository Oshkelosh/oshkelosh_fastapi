"""Tests for host self-update via git pull."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.config import Settings
from app.core.exceptions import ValidationError
from app.services import host_update


def test_host_update_disabled():
    cfg = Settings(host_self_update_enabled=False, host_repo_root="/tmp/unused")
    with pytest.raises(ValidationError, match="disabled"):
        host_update.update_host_from_git(cfg=cfg)


def test_host_update_requires_git_tree(tmp_path: Path):
    cfg = Settings(
        host_self_update_enabled=True,
        host_repo_root=str(tmp_path),
        addon_install_restart_flag_file="",
    )
    with pytest.raises(ValidationError, match="Not a git working tree"):
        host_update.update_host_from_git(cfg=cfg)


def test_host_update_rejects_dirty_tree(tmp_path: Path):
    (tmp_path / ".git").mkdir()
    cfg = Settings(
        host_self_update_enabled=True,
        host_repo_root=str(tmp_path),
        addon_install_restart_flag_file="",
    )

    def fake_run(cmd, cwd=None, check=False, capture_output=False, text=False):
        result = MagicMock()
        result.returncode = 0
        result.stderr = ""
        if cmd[:3] == ["git", "status", "--porcelain"]:
            result.stdout = " M README.md\n"
        else:
            result.stdout = "main\n"
        return result

    with patch("app.services.host_update.subprocess.run", side_effect=fake_run):
        with pytest.raises(ValidationError, match="local changes"):
            host_update.update_host_from_git(cfg=cfg)


def test_host_update_ff_only_success(tmp_path: Path):
    (tmp_path / ".git").mkdir()
    venv_pip = tmp_path / ".venv" / "bin" / "pip"
    venv_pip.parent.mkdir(parents=True)
    venv_pip.write_text("#!/bin/sh\n")
    flag = tmp_path / "restart.flag"
    cfg = Settings(
        host_self_update_enabled=True,
        host_repo_root=str(tmp_path),
        addon_install_restart_flag_file=str(flag),
        addon_install_restart_flag_format="json",
        app_version="0.1.0",
    )

    calls: list[list[str]] = []

    def fake_run(cmd, cwd=None, check=False, capture_output=False, text=False):
        calls.append(list(cmd))
        result = MagicMock()
        result.returncode = 0
        result.stderr = ""
        if cmd[:3] == ["git", "status", "--porcelain"]:
            result.stdout = ""
        elif cmd[:3] == ["git", "rev-parse", "--abbrev-ref"]:
            result.stdout = "main\n"
        elif cmd[:3] == ["git", "rev-parse", "HEAD"]:
            # first HEAD before pull, second after
            head_calls = [c for c in calls if c[:3] == ["git", "rev-parse", "HEAD"]]
            result.stdout = "aaa111\n" if len(head_calls) <= 1 else "bbb222\n"
        else:
            result.stdout = ""
        return result

    with patch("app.services.host_update.subprocess.run", side_effect=fake_run):
        result = host_update.update_host_from_git(cfg=cfg)

    assert result.previous_commit == "aaa111"
    assert result.new_commit == "bbb222"
    assert result.branch == "main"
    assert result.restart_flag_written is True
    assert flag.is_file()
    assert "bbb222" in flag.read_text()
    assert any(c[:2] == ["git", "pull"] and "--ff-only" in c for c in calls)
    assert any(c[-2:] == ["-e", "."] for c in calls)
