"""Shared helpers for addon admin save routes."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi.responses import RedirectResponse
from jinja2 import ChoiceLoader, Environment, FileSystemLoader

from app.services.addons import merge_config_updates, persist_addon_config

_ADMIN_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "admin" / "templates"


def make_addon_jinja_env(addon_templates_dir: Path) -> Environment:
    """Jinja env that resolves addon templates and shared admin base.html."""
    return Environment(
        loader=ChoiceLoader(
            [
                FileSystemLoader(str(addon_templates_dir)),
                FileSystemLoader(str(_ADMIN_TEMPLATES_DIR)),
            ]
        ),
        autoescape=True,
        trim_blocks=True,
        lstrip_blocks=True,
    )


async def save_addon_from_form(
    session: Any,
    addon_id: str,
    config_updates: dict,
    *,
    enabled: bool | None = None,
    redirect_url: str,
    flash_message: str,
) -> RedirectResponse:
    """Merge form data, persist to DB + registry, and redirect."""
    from app.addons.registry import addon_registry

    addon = addon_registry.get(addon_id)
    if addon is None:
        raise ValueError(f"Addon '{addon_id}' not found")

    if enabled is None:
        enabled = addon.is_enabled

    config = merge_config_updates(addon_id, config_updates)
    await persist_addon_config(session, addon_id, config, enabled)
    await session.commit()

    resp = RedirectResponse(url=redirect_url, status_code=302)
    resp.set_cookie(
        key="_oshkelosh_flash",
        value=flash_message,
        httponly=True,
        max_age=5,
    )
    return resp
