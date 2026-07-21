"""Scripts tool addon admin routes."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import ValidationError

from app.addons.admin_helpers import (
    make_addon_jinja_env,
    render_addon_admin_page,
    require_addon_csrf,
    save_addon_from_form,
)
from app.addons.registry import addon_registry
from app.addons.tools.scripts.config import ScriptEntry, ScriptsConfig
from app.addons.tools.scripts.parse import ScriptTagError, format_script_tag, parse_script_tag
from app.admin.routes import require_admin_session

_CONFIGURE_URL = "/admin/tools/scripts"
_TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"

jinja_env = make_addon_jinja_env(_TEMPLATES_DIR)
admin_router = APIRouter()


def _format_error(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        parts = []
        for err in exc.errors():
            loc = ".".join(str(p) for p in err.get("loc", ()) if p != "scripts")
            msg = err.get("msg", "invalid")
            parts.append(f"{loc}: {msg}" if loc else msg)
        return "; ".join(parts) or str(exc)
    return str(exc)


def _current_config() -> dict[str, Any]:
    return dict(addon_registry.get_config("scripts") or {})


def _scripts_list(config: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    cfg = config if config is not None else _current_config()
    scripts = cfg.get("scripts") or []
    return [dict(s) for s in scripts]


def _page(
    request: Request,
    *,
    flash: str | None = None,
    flash_type: str = "info",
    edit_id: str | None = None,
    form_error: str | None = None,
    form_values: dict[str, Any] | None = None,
) -> HTMLResponse:
    addon = addon_registry.get("scripts")
    config = _current_config()
    scripts = _scripts_list(config)
    for entry in scripts:
        entry["tag"] = format_script_tag(entry.get("src", ""), entry.get("attrs") or {})

    edit_entry = None
    if edit_id:
        edit_entry = next((s for s in scripts if s.get("id") == edit_id), None)

    return HTMLResponse(
        content=render_addon_admin_page(
            jinja_env,
            request,
            "scripts_settings.html",
            "Scripts",
            flash=flash or form_error,
            flash_type="error" if form_error else flash_type,
            addon=addon,
            config=config,
            scripts=scripts,
            edit_entry=edit_entry,
            form_values=form_values or {},
        ),
    )


@admin_router.get("")
async def scripts_settings_page(request: Request, db=Depends(require_admin_session)):
    edit_id = request.query_params.get("edit") or None
    return _page(request, edit_id=edit_id)


@admin_router.get("/", include_in_schema=False)
async def scripts_trailing_slash_redirect():
    return RedirectResponse(url=_CONFIGURE_URL, status_code=307)


@admin_router.post("/settings")
async def scripts_save_settings(request: Request, db=Depends(require_admin_session)):
    form = await request.form()
    require_addon_csrf(request, str(form.get("csrf_token", "")))
    enabled = form.get("is_enabled") == "on"
    # Preserve existing scripts; only toggle enable.
    config = {"scripts": _scripts_list()}
    try:
        return await save_addon_from_form(
            db,
            "scripts",
            config,
            enabled=enabled,
            redirect_url=_CONFIGURE_URL,
            flash_message="Scripts addon settings saved",
        )
    except Exception as exc:
        return _page(request, form_error=f"Error saving settings: {exc}")


@admin_router.post("/add")
async def scripts_add(request: Request, db=Depends(require_admin_session)):
    form = await request.form()
    require_addon_csrf(request, str(form.get("csrf_token", "")))

    name = str(form.get("name", "") or "").strip()
    tag = str(form.get("tag", "") or "")
    routes = str(form.get("routes", "all") or "all").strip()
    enabled = form.get("enabled") == "on"
    form_values = {"name": name, "tag": tag, "routes": routes, "enabled": enabled}

    try:
        src, attrs = parse_script_tag(tag)
        entry = ScriptEntry(
            id=uuid.uuid4().hex,
            name=name or "Script",
            enabled=enabled,
            routes=routes,  # type: ignore[arg-type]
            src=src,
            attrs=attrs,
        )
        scripts = _scripts_list()
        scripts.append(entry.model_dump())
        ScriptsConfig(scripts=scripts)  # validate
        addon = addon_registry.get("scripts")
        keep_enabled = bool(addon and addon.is_enabled)
        return await save_addon_from_form(
            db,
            "scripts",
            {"scripts": scripts},
            enabled=keep_enabled,
            redirect_url=_CONFIGURE_URL,
            flash_message="Script added",
        )
    except (ScriptTagError, ValueError, ValidationError) as exc:
        return _page(request, form_error=_format_error(exc), form_values=form_values)


@admin_router.post("/{script_id}/save")
async def scripts_save(script_id: str, request: Request, db=Depends(require_admin_session)):
    form = await request.form()
    require_addon_csrf(request, str(form.get("csrf_token", "")))

    name = str(form.get("name", "") or "").strip()
    tag = str(form.get("tag", "") or "")
    routes = str(form.get("routes", "all") or "all").strip()
    enabled = form.get("enabled") == "on"
    form_values = {"name": name, "tag": tag, "routes": routes, "enabled": enabled}

    scripts = _scripts_list()
    idx = next((i for i, s in enumerate(scripts) if s.get("id") == script_id), None)
    if idx is None:
        return _page(request, form_error="Script not found")

    try:
        src, attrs = parse_script_tag(tag)
        entry = ScriptEntry(
            id=script_id,
            name=name or "Script",
            enabled=enabled,
            routes=routes,  # type: ignore[arg-type]
            src=src,
            attrs=attrs,
        )
        scripts[idx] = entry.model_dump()
        ScriptsConfig(scripts=scripts)
        addon = addon_registry.get("scripts")
        keep_enabled = bool(addon and addon.is_enabled)
        return await save_addon_from_form(
            db,
            "scripts",
            {"scripts": scripts},
            enabled=keep_enabled,
            redirect_url=_CONFIGURE_URL,
            flash_message="Script updated",
        )
    except (ScriptTagError, ValueError, ValidationError) as exc:
        return _page(
            request,
            form_error=_format_error(exc),
            edit_id=script_id,
            form_values=form_values,
        )


@admin_router.post("/{script_id}/delete")
async def scripts_delete(script_id: str, request: Request, db=Depends(require_admin_session)):
    form = await request.form()
    require_addon_csrf(request, str(form.get("csrf_token", "")))

    scripts = [s for s in _scripts_list() if s.get("id") != script_id]
    addon = addon_registry.get("scripts")
    keep_enabled = bool(addon and addon.is_enabled)
    return await save_addon_from_form(
        db,
        "scripts",
        {"scripts": scripts},
        enabled=keep_enabled,
        redirect_url=_CONFIGURE_URL,
        flash_message="Script deleted",
    )
