"""Update the host Oshkelosh install via git pull and pip install."""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from app.config import Settings, settings
from app.core.exceptions import ValidationError


@dataclass(frozen=True)
class HostUpdateResult:
    previous_commit: str
    new_commit: str
    branch: str
    restart_flag_written: bool
    restart_flag_path: str | None


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _run_git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip() or f"exit {completed.returncode}"
        raise ValidationError(message=f"git {' '.join(args)} failed: {detail}")
    return (completed.stdout or "").strip()


def _write_host_restart_flag(cfg: Settings, *, previous: str, new: str, branch: str) -> Path | None:
    flag_path = cfg.addon_install_restart_flag_path
    if flag_path is None:
        return None

    flag_path.parent.mkdir(parents=True, exist_ok=True)
    installed_at = _utc_now_iso()
    if cfg.addon_install_restart_flag_format == "text":
        payload = f"host_updated {branch} {previous} {new} {installed_at}\n"
    else:
        payload = json.dumps(
            {
                "reason": "host_updated",
                "branch": branch,
                "previous_commit": previous,
                "new_commit": new,
                "updated_at": installed_at,
                "host_version": cfg.app_version,
            },
            indent=2,
        ) + "\n"

    tmp_path = flag_path.with_suffix(flag_path.suffix + ".tmp")
    tmp_path.write_text(payload, encoding="utf-8")
    os.replace(tmp_path, flag_path)
    return flag_path


def update_host_from_git(*, cfg: Settings | None = None) -> HostUpdateResult:
    """Fast-forward pull the host git repo, reinstall editable package, write restart flag."""
    cfg = cfg or settings
    if not cfg.host_self_update_enabled:
        raise ValidationError(message="Host self-update is disabled (HOST_SELF_UPDATE_ENABLED=false)")

    repo = cfg.host_repo_root_path
    if not (repo / ".git").exists():
        raise ValidationError(message=f"Not a git working tree: {repo}")

    status = _run_git(repo, "status", "--porcelain")
    if status:
        raise ValidationError(
            message="Working tree has local changes; commit or stash before updating"
        )

    branch = _run_git(repo, "rev-parse", "--abbrev-ref", "HEAD")
    if not branch or branch == "HEAD":
        raise ValidationError(message="Detached HEAD is not supported for host self-update")

    previous = _run_git(repo, "rev-parse", "HEAD")
    _run_git(repo, "fetch", "--prune", "origin")
    _run_git(repo, "pull", "--ff-only", "origin", branch)
    new = _run_git(repo, "rev-parse", "HEAD")

    pip = repo / ".venv" / "bin" / "pip"
    if not pip.is_file():
        raise ValidationError(message=f"Expected virtualenv pip at {pip}")

    completed = subprocess.run(
        [str(pip), "install", "-e", "."],
        cwd=repo,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip() or f"exit {completed.returncode}"
        raise ValidationError(message=f"pip install -e . failed: {detail}")

    flag_path = _write_host_restart_flag(cfg, previous=previous, new=new, branch=branch)
    return HostUpdateResult(
        previous_commit=previous,
        new_commit=new,
        branch=branch,
        restart_flag_written=flag_path is not None,
        restart_flag_path=str(flag_path) if flag_path else None,
    )
