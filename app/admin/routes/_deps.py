"""Shared dependencies and template helpers for admin HTML routes."""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import urlencode

from fastapi import APIRouter, Cookie, Depends, File, Form, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col

from app.admin import limits as L
from app.config import settings
from app.core.rate_limit import limiter
from app.admin.session import (
    FLASH_COOKIE_NAME,
    SESSION_COOKIE_NAME,
    clear_session_cookie,
    decode_session,
    set_flash_cookie,
    set_session_cookie,
)
from app.core.exceptions import NotFound
from app.core.security import verify_password
from app.db.connection import get_session, mark_instance_dirty

# Jinja2 setup
# ------------------------------------------------------------------

_ADMIN_DIR = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = _ADMIN_DIR / "templates"
STATIC_DIR = _ADMIN_DIR / "static"

from jinja2 import Environment, FileSystemLoader, select_autoescape

jinja_env = Environment(
    loader=FileSystemLoader(str(TEMPLATES_DIR)),
    autoescape=select_autoescape(default=True, default_for_string=True),
    trim_blocks=True,
    lstrip_blocks=True,
)


_SETUP_PATH = "/setup"


def _redirect_to_setup() -> None:
    raise HTTPException(
        status_code=status.HTTP_307_TEMPORARY_REDIRECT,
        headers={"Location": _SETUP_PATH},
    )


def _redirect_to_login() -> None:
    raise HTTPException(
        status_code=status.HTTP_307_TEMPORARY_REDIRECT,
        headers={"Location": f"{settings.admin_prefix}/login"},
    )


def _needs_setup(request: Request) -> bool:
    return getattr(request.app.state, "needs_setup", False)


def _require_csrf(request: Request, csrf_token: str) -> None:
    expected = getattr(request.state, "csrf_token", None)
    if not expected or csrf_token != expected:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid CSRF token")


async def require_admin_session(
    request: Request,
    db=Depends(get_session),
    session_token: Optional[str] = Cookie(None, alias=SESSION_COOKIE_NAME),
):
    """Verify the admin session cookie and return the request DB session."""
    if _needs_setup(request):
        from app.services.bootstrap import has_admin_user

        if await has_admin_user(db):
            request.app.state.needs_setup = False
        else:
            _redirect_to_setup()

    if not session_token:
        _redirect_to_login()

    payload = decode_session(session_token)
    if not payload or payload.get("type") != "admin_session":
        _redirect_to_login()

    try:
        user_id = int(payload["sub"])
    except (KeyError, TypeError, ValueError):
        _redirect_to_login()

    from models.user import User

    user = await db.get(User, user_id)
    if not user or not user.is_admin or user.banned or not user.verified:
        _redirect_to_login()

    request.state.admin_user = user
    request.state.csrf_token = payload.get("csrf")

    from app.services.site_settings import get_site_settings

    request.state.site_settings = await get_site_settings(db)
    return db


def _template(template_name: str, **context: Any):
    """Render a template and return a ``HTMLResponse``."""
    from fastapi.responses import HTMLResponse

    t = jinja_env.get_template(template_name)
    html = t.render(**context)
    return HTMLResponse(content=html, status_code=200)


def _common_ctx(request: Request, title: str, flash: str | None = None) -> Dict[str, Any]:
    """Common template context for every admin page."""
    from app.addons.registry import addon_registry
    from app.services.addons import get_frontend_addon

    user = getattr(request.state, "admin_user", None)
    site_settings = getattr(request.state, "site_settings", None)
    store_name = site_settings.store_name if site_settings else settings.app_name
    if flash is None:
        from app.admin.session import read_flash_cookie

        flash = read_flash_cookie(request.cookies.get(FLASH_COOKIE_NAME, ""))
    addon_nav_items: list = []
    for addon in addon_registry.iter_addons():
        if not addon.is_enabled:
            continue
        addon_nav_items.extend(addon.get_admin_nav_items())
    return {
        "request": request,
        "title": title,
        "user": user,
        "flash": flash,
        "flash_type": "info",
        "admin_prefix": settings.admin_prefix,
        "settings": settings,
        "site_settings": site_settings,
        "store_name": store_name,
        "storefront_url": "/",
        "storefront_available": get_frontend_addon() is not None,
        "csrf_token": getattr(request.state, "csrf_token", ""),
        "addon_nav_items": addon_nav_items,
    }


def _render_error(
    request: Request, message: str, flash_type: str = "error", status_code: int = 200
):
    from fastapi.responses import HTMLResponse

    ctx = _common_ctx(request, "Error", message)
    ctx["flash_type"] = flash_type
    return HTMLResponse(
        content=jinja_env.get_template("error.html").render(**ctx),
        status_code=status_code,
    )


async def _render_product_form(
    request: Request,
    db: AsyncSession | None,
    *,
    title: str,
    product: Any,
    action_url: str,
    supplier_value: str,
    supplier_product_id: str,
    supplier_variant_id: str,
    other_tags_json: str,
    flash: str | None = None,
    flash_type: str = "info",
    product_is_sync_imported: bool = False,
    supplier_label: str = "",
    product_images: list[Any] | None = None,
    product_variants: list[Any] | None = None,
    product_options_json: str = "{}",
):
    """Render the product create/edit form with supplier fields."""
    import json

    from app.services.suppliers import build_supplier_form_meta, list_supplier_options
    from models.category import Category

    categories = []
    supplier_options = []
    supplier_form_meta = build_supplier_form_meta()
    if db is not None:
        try:
            cat_result = await db.execute(select(Category).order_by(col(Category.sort_order).asc()))
            categories = cat_result.scalars().all()
            supplier_options = await list_supplier_options(db)
        except Exception:
            pass

    ctx = _common_ctx(request, title, flash=flash or "")
    ctx["flash_type"] = flash_type
    return _template(
        "product_form.html",
        **ctx,
        product=product,
        categories=categories,
        supplier_options=supplier_options,
        supplier_form_meta_json=json.dumps(supplier_form_meta),
        supplier_value=supplier_value,
        supplier_product_id=supplier_product_id,
        supplier_variant_id=supplier_variant_id,
        other_tags_json=other_tags_json,
        action_url=action_url,
        product_is_sync_imported=product_is_sync_imported,
        supplier_label=supplier_label,
        product_images=product_images or [],
        product_variants=product_variants or [],
        product_options_json=product_options_json,
    )


__all__ = [
    "FLASH_COOKIE_NAME",
    "SESSION_COOKIE_NAME",
    "STATIC_DIR",
    "TEMPLATES_DIR",
    "_SETUP_PATH",
    "_common_ctx",
    "_needs_setup",
    "_redirect_to_login",
    "_redirect_to_setup",
    "_render_error",
    "_render_product_form",
    "_require_csrf",
    "_template",
    "Any",
    "AsyncSession",
    "Cookie",
    "Depends",
    "Dict",
    "File",
    "Form",
    "HTTPException",
    "Optional",
    "Query",
    "RedirectResponse",
    "Request",
    "UploadFile",
    "clear_session_cookie",
    "col",
    "decode_session",
    "func",
    "get_session",
    "jinja_env",
    "json",
    "limiter",
    "mark_instance_dirty",
    "require_admin_session",
    "select",
    "set_flash_cookie",
    "set_session_cookie",
    "settings",
    "status",
    "verify_password",
    "datetime",
    "timedelta",
    "timezone",
    "urlencode",
]

