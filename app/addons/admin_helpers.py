"""Shared helpers for addon admin save routes."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import Request
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


def redact_secret_values(config: dict[str, Any], *keys: str) -> dict[str, Any]:
    """Return a copy of config with secret string values partially masked."""
    redacted = dict(config)
    for key in keys:
        val = redacted.get(key)
        if isinstance(val, str) and val:
            redacted[key] = val[:8] + "…" if len(val) > 8 else "***"
    return redacted


def render_addon_admin_page(
    jinja_env: Environment,
    request: Request,
    template_name: str,
    title: str,
    *,
    flash: str | None = None,
    flash_type: str = "info",
    **extra: Any,
) -> str:
    """Render an addon admin template with shared admin context.

    ``flash`` and ``flash_type`` are merged into ``_common_ctx`` output without
    duplicating keyword arguments (which breaks Jinja ``render()``).
    """
    from app.admin.routes import _common_ctx

    ctx = _common_ctx(request, title, flash=flash)
    ctx["flash_type"] = flash_type
    ctx.update(extra)
    return jinja_env.get_template(template_name).render(**ctx)


def require_addon_csrf(request: Request, csrf_token: str) -> None:
    """Validate CSRF token on addon admin POST handlers."""
    from app.admin.routes import _require_csrf

    _require_csrf(request, csrf_token)


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
    from app.admin.session import set_flash_cookie

    addon = addon_registry.get(addon_id)
    if addon is None:
        raise ValueError(f"Addon '{addon_id}' not found")

    if enabled is None:
        enabled = addon.is_enabled

    config = merge_config_updates(addon_id, config_updates)
    await persist_addon_config(session, addon_id, config, enabled)
    await session.commit()

    resp = RedirectResponse(url=redirect_url, status_code=302)
    set_flash_cookie(resp, flash_message)
    return resp
