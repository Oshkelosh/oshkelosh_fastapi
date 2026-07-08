"""Resolve which storefront frontend serves a given HTTP request."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from starlette.requests import Request

from app.addons.frontends.base import FrontendAddon
from app.services.addons import get_frontend_addon

_LEGACY_DIST = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"


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


def resolve_frontend_addon(request: Request | None = None) -> FrontendAddon | None:
    """Pick which frontend serves this request.

    Default: the admin-selected active frontend. ``request`` is accepted now so
    future A/B rules can inspect cookies, headers, or query params.
    """
    del request  # reserved for future A/B routing
    return get_frontend_addon()


def resolve_static_directory(request: Request | None = None) -> Path | None:
    """Return the filesystem path to serve for this request, or None."""
    frontend = resolve_frontend_addon(request)
    if frontend is not None:
        dist = Path(frontend.get_static_directory())
        if dist.is_dir() and (dist / "index.html").is_file():
            return dist

    if _LEGACY_DIST.is_dir() and (_LEGACY_DIST / "index.html").is_file():
        return _LEGACY_DIST

    return None
