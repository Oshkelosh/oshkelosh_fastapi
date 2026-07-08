"""Shared admin route factory for notification addons."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.addons.admin_helpers import (
    make_addon_jinja_env,
    redact_secret_values,
    render_addon_admin_page,
    save_addon_from_form,
)
from app.addons.registry import addon_registry
from app.admin.routes import require_admin_session


def build_notification_routers(
    addon_id: str,
    *,
    template_name: str,
    page_title: str,
    secret_keys: tuple[str, ...] = (),
    parse_config_form: Callable[[Any], tuple[dict[str, Any], bool]],
) -> tuple[APIRouter, Any]:
    """Return (admin_router, jinja_env) for a notification addon."""
    templates_dir = Path(__file__).resolve().parent / addon_id / "templates"
    jinja_env = make_addon_jinja_env(templates_dir)
    configure_url = f"/admin/notifications/{addon_id}"

    admin_router = APIRouter()

    def _masked_config(addon: Any) -> dict[str, Any]:
        if addon and hasattr(addon, "_config") and addon._config:
            return redact_secret_values(dict(addon._config), *secret_keys)
        return {}

    @admin_router.get("")
    async def config_page(request: Request, db=Depends(require_admin_session)):
        addon = addon_registry.get(addon_id)
        return HTMLResponse(
            content=render_addon_admin_page(
                jinja_env,
                request,
                template_name,
                page_title,
                addon=addon,
                config=_masked_config(addon),
                configure_url=configure_url,
            ),
        )

    @admin_router.get("/", include_in_schema=False)
    async def config_trailing_slash_redirect():
        return RedirectResponse(url=configure_url, status_code=307)

    @admin_router.post("/save")
    async def save_config(request: Request, db=Depends(require_admin_session)):
        from app.addons.admin_helpers import require_addon_csrf

        try:
            form = await request.form()
            require_addon_csrf(request, str(form.get("csrf_token", "")))
            config, enabled = parse_config_form(form)
            return await save_addon_from_form(
                db,
                addon_id,
                config,
                enabled=enabled,
                redirect_url=configure_url,
                flash_message=f"{page_title} saved",
            )
        except Exception as exc:
            addon = addon_registry.get(addon_id)
            return HTMLResponse(
                content=render_addon_admin_page(
                    jinja_env,
                    request,
                    template_name,
                    page_title,
                    flash=f"Error saving config: {exc}",
                    flash_type="error",
                    addon=addon,
                    config=_masked_config(addon),
                    configure_url=configure_url,
                ),
            )

    return admin_router, jinja_env
