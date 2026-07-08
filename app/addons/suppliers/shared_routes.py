"""Shared admin/API route factories for supplier addons."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from app.addons.log import exception
from app.addons.admin_helpers import (
    make_addon_jinja_env,
    redact_secret_values,
    render_addon_admin_page,
    require_addon_csrf,
)
from app.admin.routes import _require_csrf, require_admin_session
from app.services.supplier_catalog_sync import SupplierCatalogSyncOptions, sync_supplier_catalog


def build_supplier_routers(
    addon_id: str,
    *,
    template_name: str,
    page_title: str,
    secret_keys: tuple[str, ...] = ("api_key",),
    parse_config_form: Callable[[Any], tuple[dict[str, Any], bool]],
) -> tuple[APIRouter, APIRouter, Any]:
    """Return (admin_router, api_router, jinja_env) for a supplier addon."""
    templates_dir = Path(__file__).resolve().parent / addon_id / "templates"
    jinja_env = make_addon_jinja_env(templates_dir)
    configure_url = f"/admin/suppliers/{addon_id}"

    admin_router = APIRouter()
    api_router = APIRouter()

    def _masked_config(addon: Any) -> dict[str, Any]:
        if addon and hasattr(addon, "_config") and addon._config:
            return redact_secret_values(dict(addon._config), *secret_keys)
        return {}

    @admin_router.get("")
    async def config_page(request: Request, db=Depends(require_admin_session)):
        from app.addons.registry import addon_registry

        addon = addon_registry.get(addon_id)
        return HTMLResponse(
            content=render_addon_admin_page(
                jinja_env,
                request,
                template_name,
                page_title,
                addon=addon,
                config=_masked_config(addon),
            ),
        )

    @admin_router.get("/", include_in_schema=False)
    async def config_trailing_slash_redirect():
        return RedirectResponse(url=configure_url, status_code=307)

    @admin_router.post("/save")
    async def save_config(request: Request, db=Depends(require_admin_session)):
        from app.addons.admin_helpers import save_addon_from_form
        from app.addons.registry import addon_registry

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
                ),
            )

    @admin_router.post("/sync")
    async def sync_catalog(
        request: Request,
        import_status: str = Form("draft", max_length=32),
        archive_missing: str = Form(""),
        csrf_token: str = Form(..., max_length=128),
        db=Depends(require_admin_session),
    ):
        from app.admin.session import set_flash_cookie

        _require_csrf(request, csrf_token)
        try:
            result = await sync_supplier_catalog(
                db,
                addon_id,
                SupplierCatalogSyncOptions(
                    import_status=import_status if import_status in ("draft", "published") else "draft",
                    archive_missing=archive_missing == "on",
                ),
                actor_user_id=request.state.admin_user.id,
                ip_address=request.client.host if request.client else None,
            )
            flash = result.summary_message()
        except Exception as exc:
            flash = f"Sync failed: {exc}"

        resp = RedirectResponse(url=configure_url, status_code=302)
        set_flash_cookie(resp, flash)
        return resp

    @api_router.get("/products")
    async def list_products_route(db=Depends(require_admin_session)):
        from app.addons.registry import addon_registry

        addon = addon_registry.get(addon_id)
        if addon is None or not addon.is_enabled:
            return JSONResponse(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                content={"error": f"{page_title} addon is not enabled"},
            )
        try:
            products = await addon.list_products()
            return JSONResponse(content={"products": products})
        except Exception as exc:
            exception(page_title, "list_products failed: {}", exc)
            return JSONResponse(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                content={"error": str(exc)},
            )

    return admin_router, api_router, jinja_env


def parse_standard_api_key_form(form: Any) -> tuple[dict[str, Any], bool]:
    return {
        "api_key": form.get("api_key", ""),
        "is_active": form.get("is_active") == "on",
    }, form.get("is_active") == "on"


def supplier_config_template(
    addon_name: str,
    addon_id: str,
    *,
    extra_fields: str = "",
    catalog_blurb: str = "",
) -> str:
    """Return Jinja HTML for a standard supplier config + sync page."""
    blurb = catalog_blurb or (
        f"Import {addon_name} catalog items into Oshkelosh products. "
        "Re-sync updates name, price, SKU, and supplier tags."
    )
    return f"""{{% extends "base.html" %}}

{{% block title %}}{addon_name} Settings{{% endblock %}}

{{% block content %}}
<h1>{addon_name} Supplier</h1>

<div class="card">
    <h2>Configuration</h2>
    {{% if config %}}
    <div class="alert alert--info" style="margin-bottom:1em;">
        <strong>Status:</strong> {{% if addon and addon.is_enabled %}}Enabled{{% else %}}Disabled{{% endif %}}
    </div>
    {{% endif %}}

    <form method="post" action="/admin/suppliers/{addon_id}/save" class="form">
        <input type="hidden" name="csrf_token" value="{{{{ csrf_token }}}}">

        <div class="form-group">
            <label for="api_key">API Key</label>
            <input type="password" id="api_key" name="api_key"
                   value="{{{{ config.get('api_key', '') }}}}"
                   placeholder="{addon_name} API key" />
        </div>

        {extra_fields}

        <div class="form-group">
            <label>
                <input type="checkbox" name="is_active" {{% if config.get('is_active') %}}checked{{% endif %}} />
                Active
            </label>
        </div>

        <div class="form-actions">
            <button type="submit" class="btn btn--primary">Save Configuration</button>
        </div>
    </form>
</div>

<div class="card" style="margin-top:1.5em;">
    <h2>Catalog sync</h2>
    <p style="color:var(--clr-text-muted);margin-bottom:12px;">{blurb}</p>
    <form method="post" action="/admin/suppliers/{addon_id}/sync" class="form">
        <input type="hidden" name="csrf_token" value="{{{{ csrf_token }}}}">
        <div class="form-group">
            <label for="import_status">Import as</label>
            <select id="import_status" name="import_status">
                <option value="draft" selected>Draft</option>
                <option value="published">Published</option>
            </select>
        </div>
        <div class="form-group">
            <label>
                <input type="checkbox" name="archive_missing" />
                Archive local products no longer in remote catalog
            </label>
        </div>
        <div class="form-actions">
            <button type="submit" class="btn btn--secondary">Sync catalog now</button>
        </div>
    </form>
</div>

<p style="margin-top:24px;">
  <a href="/admin/suppliers">← Back to suppliers</a>
</p>
{{% endblock %}}
"""
