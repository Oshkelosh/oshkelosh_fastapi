"""
Manual supplier addon routes.

Admin Router (mounted at /admin/suppliers/manual/*):
    GET  /admin/suppliers/manual              - List manual suppliers
    GET  /admin/suppliers/manual/new          - Add form
    POST /admin/suppliers/manual/create       - Create supplier
    GET  /admin/suppliers/manual/{slug}/edit  - Edit form
    POST /admin/suppliers/manual/{slug}/save  - Update supplier
    POST /admin/suppliers/manual/{slug}/delete - Delete supplier
    POST /admin/suppliers/manual/settings     - Enable/disable addon
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.addons.admin_helpers import make_addon_jinja_env, render_addon_admin_page, save_addon_from_form
from app.addons.suppliers.manual.addon import ManualSupplierAddon, normalize_manual_slug
from app.admin.routes import require_admin_session
from app.core.dependencies import get_admin_user
from app.services.manual_suppliers import get_manual_supplier, list_manual_suppliers
from models.manual_supplier import ManualSupplier

_ADDON_TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
_CONFIGURE_URL = "/admin/suppliers/manual"

jinja_env = make_addon_jinja_env(_ADDON_TEMPLATES_DIR)

admin_router = APIRouter()
api_router = APIRouter()


def _slugify(name: str) -> str:
    slug = name.strip().lower().replace(" ", "_").replace("-", "_")
    slug = re.sub(r"[^a-z0-9_]", "", slug)
    return slug


@admin_router.get("")
async def manual_suppliers_list(request: Request, db=Depends(require_admin_session)):
    from app.addons.registry import addon_registry

    addon = addon_registry.get("manual")
    suppliers: list[ManualSupplier] = []
    if db is not None:
        suppliers = await list_manual_suppliers(db)

    return HTMLResponse(
        content=render_addon_admin_page(
            jinja_env,
            request,
            "manual_list.html",
            "Manual Suppliers",
            addon=addon,
            suppliers=suppliers,
        ),
    )


@admin_router.get("/", include_in_schema=False)
async def manual_trailing_slash_redirect():
    return RedirectResponse(url=_CONFIGURE_URL, status_code=307)


@admin_router.get("/new")
async def manual_supplier_new(request: Request, db=Depends(require_admin_session)):
    return HTMLResponse(
        content=render_addon_admin_page(
            jinja_env,
            request,
            "manual_form.html",
            "New Manual Supplier",
            supplier=None,
            action_url="/admin/suppliers/manual/create",
        ),
    )


@admin_router.post("/create")
async def manual_supplier_create(
    request: Request,
    name: str = Form(..., max_length=255),
    slug: str = Form("", max_length=100),
    contact_email: str = Form("", max_length=255),
    contact_phone: str = Form("", max_length=50),
    notes: str = Form("", max_length=2000),
    is_active: str = Form("on"),
    csrf_token: str = Form(...),
    db=Depends(require_admin_session),
):
    from app.admin.routes import _require_csrf

    _require_csrf(request, csrf_token)

    try:
        normalized_slug = normalize_manual_slug(slug or _slugify(name))
    except ValueError as exc:
        return HTMLResponse(
            content=render_addon_admin_page(
                jinja_env,
                request,
                "manual_form.html",
                "New Manual Supplier",
                flash=str(exc),
                flash_type="error",
                supplier=None,
                action_url="/admin/suppliers/manual/create",
                form={
                    "name": name,
                    "slug": slug,
                    "contact_email": contact_email,
                    "contact_phone": contact_phone,
                    "notes": notes,
                },
            ),
            status_code=400,
        )

    if await get_manual_supplier(db, normalized_slug) is not None:
        return HTMLResponse(
            content=render_addon_admin_page(
                jinja_env,
                request,
                "manual_form.html",
                "New Manual Supplier",
                flash="Slug already exists",
                flash_type="error",
                supplier=None,
                action_url="/admin/suppliers/manual/create",
                form={"name": name, "slug": normalized_slug},
            ),
            status_code=400,
        )

    row = ManualSupplier(
        slug=normalized_slug,
        name=name.strip(),
        contact_email=contact_email.strip() or None,
        contact_phone=contact_phone.strip() or None,
        notes=notes.strip() or None,
        is_active=is_active == "on",
    )
    db.add(row)
    await db.commit()

    resp = RedirectResponse(url=_CONFIGURE_URL, status_code=302)
    from app.admin.routes import set_flash_cookie

    set_flash_cookie(resp, f"Manual supplier '{row.name}' created")
    return resp


@admin_router.get("/{slug}/edit")
async def manual_supplier_edit(
    request: Request,
    slug: str,
    db=Depends(require_admin_session),
):
    supplier = await get_manual_supplier(db, slug)
    if supplier is None:
        return RedirectResponse(url=_CONFIGURE_URL, status_code=302)

    return HTMLResponse(
        content=render_addon_admin_page(
            jinja_env,
            request,
            "manual_form.html",
            f"Edit: {supplier.name}",
            supplier=supplier,
            action_url=f"/admin/suppliers/manual/{slug}/save",
        ),
    )


@admin_router.post("/{slug}/save")
async def manual_supplier_save(
    request: Request,
    slug: str,
    name: str = Form(..., max_length=255),
    contact_email: str = Form("", max_length=255),
    contact_phone: str = Form("", max_length=50),
    notes: str = Form("", max_length=2000),
    is_active: str = Form("on"),
    csrf_token: str = Form(...),
    db=Depends(require_admin_session),
):
    from app.admin.routes import _require_csrf, set_flash_cookie

    _require_csrf(request, csrf_token)

    supplier = await get_manual_supplier(db, slug)
    if supplier is None:
        return RedirectResponse(url=_CONFIGURE_URL, status_code=302)

    supplier.name = name.strip()
    supplier.contact_email = contact_email.strip() or None
    supplier.contact_phone = contact_phone.strip() or None
    supplier.notes = notes.strip() or None
    supplier.is_active = is_active == "on"
    await db.commit()

    resp = RedirectResponse(url=_CONFIGURE_URL, status_code=302)
    set_flash_cookie(resp, f"Manual supplier '{supplier.name}' updated")
    return resp


@admin_router.post("/{slug}/delete")
async def manual_supplier_delete(
    request: Request,
    slug: str,
    csrf_token: str = Form(...),
    db=Depends(require_admin_session),
):
    from app.admin.routes import _require_csrf, set_flash_cookie

    _require_csrf(request, csrf_token)

    supplier = await get_manual_supplier(db, slug)
    if supplier is not None:
        name = supplier.name
        await db.delete(supplier)
        await db.commit()
        resp = RedirectResponse(url=_CONFIGURE_URL, status_code=302)
        set_flash_cookie(resp, f"Manual supplier '{name}' deleted")
        return resp
    return RedirectResponse(url=_CONFIGURE_URL, status_code=302)


@admin_router.post("/settings")
async def manual_addon_settings(
    request: Request,
    is_active: str = Form(""),
    csrf_token: str = Form(...),
    db=Depends(require_admin_session),
):
    from app.admin.routes import _require_csrf

    _require_csrf(request, csrf_token)

    enabled = is_active == "on"
    config: dict[str, Any] = {"is_active": enabled}
    return await save_addon_from_form(
        db,
        "manual",
        config,
        enabled=enabled,
        redirect_url=_CONFIGURE_URL,
        flash_message="Manual supplier settings saved",
    )


@api_router.get("/suppliers")
async def list_manual_suppliers_api(
    _admin=Depends(get_admin_user),
):
    from app.addons.registry import addon_registry

    addon = addon_registry.get("manual")
    if addon is None or not addon.is_enabled:
        return {"suppliers": []}
    suppliers = await addon.list_products()
    return {"suppliers": suppliers}
