"""Resolve which storefront frontend serves HTTP requests."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.addons.frontends.base import FrontendAddon
from app.services.addons import get_frontend_addon


def get_public_frontend_config(frontend: object) -> dict[str, Any]:
    """Return storefront-safe frontend addon configuration (secrets stripped)."""
    raw: dict[str, Any] = {}
    if hasattr(frontend, "_config") and frontend._config:
        raw = dict(frontend._config)

    secret_markers = ("secret", "token", "password", "api_key", "private_key")
    return {
        key: value
        for key, value in raw.items()
        if not any(marker in key.lower() for marker in secret_markers)
    }


def resolve_frontend_addon() -> FrontendAddon | None:
    """Return the admin-selected active frontend, or None."""
    return get_frontend_addon()


def resolve_static_directory() -> Path | None:
    """Return the active frontend's static bundle path, or None."""
    frontend = resolve_frontend_addon()
    if frontend is not None:
        dist = Path(frontend.get_static_directory())
        if dist.is_dir() and (dist / "index.html").is_file():
            return dist
    return None
