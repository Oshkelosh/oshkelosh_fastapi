"""
Admin router – all /admin/* endpoints for the server-rendered admin panel.

Authentication: cookie-based session with an encrypted JWT stored in the
``oshkelosh_admin`` cookie.  Every route (except login/logout) calls
``require_admin_session`` which decodes the cookie and fetches the User
from the database.

Template rendering uses ``jinja2.Environment`` with the templates
directory relative to this file.  Static files are served through a
dedicated ``GET /admin/static/{path:path}`` route.
"""

import json
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, Cookie, Depends, File, Form, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col

from app.admin import limits as L
from app.admin.session import (
    FLASH_COOKIE_NAME,
    SESSION_COOKIE_NAME,
    clear_session_cookie,
    decode_session,
    set_flash_cookie,
    set_session_cookie,
)
from app.config import settings
from app.core.exceptions import NotFound
from app.core.security import verify_password
from app.db.connection import get_session, mark_instance_dirty

# ------------------------------------------------------------------
# Jinja2 setup
# ------------------------------------------------------------------

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
STATIC_DIR = Path(__file__).resolve().parent / "static"

from jinja2 import Environment, FileSystemLoader, select_autoescape

jinja_env = Environment(
    loader=FileSystemLoader(str(TEMPLATES_DIR)),
    autoescape=select_autoescape(default=True, default_for_string=True),
    trim_blocks=True,
    lstrip_blocks=True,
)

# ------------------------------------------------------------------
# Session / redirect helpers
# ------------------------------------------------------------------

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
    if not user or not user.is_admin or not user.is_active:
        _redirect_to_login()

    request.state.admin_user = user
    request.state.csrf_token = payload.get("csrf")

    from app.services.site_settings import get_site_settings

    request.state.site_settings = await get_site_settings(db)
    return db


# ------------------------------------------------------------------
# Router
# ------------------------------------------------------------------

router = APIRouter()

# ------------------------------------------------------------------
# Shared helpers used by route handlers
# ------------------------------------------------------------------

def _template(template_name: str, **context: Any):
    """Render a template and return a ``HTMLResponse``."""
    from fastapi.responses import HTMLResponse

    t = jinja_env.get_template(template_name)
    html = t.render(**context)
    return HTMLResponse(content=html, status_code=200)


def _common_ctx(request: Request, title: str, flash: str | None = None) -> Dict[str, Any]:
    """Common template context for every admin page."""
    from app.services.addons import get_frontend_addon

    user = getattr(request.state, "admin_user", None)
    site_settings = getattr(request.state, "site_settings", None)
    store_name = site_settings.store_name if site_settings else settings.app_name
    if flash is None:
        flash = request.cookies.get(FLASH_COOKIE_NAME, "")
    return {
        "request": request,
        "title": title,
        "user": user,
        "flash": flash,
        "flash_type": "info",
        "settings": settings,
        "site_settings": site_settings,
        "store_name": store_name,
        "storefront_url": "/",
        "storefront_available": get_frontend_addon() is not None,
        "csrf_token": getattr(request.state, "csrf_token", ""),
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


# ------------------------------------------------------------------
# Authentication
# ------------------------------------------------------------------

@router.get("/login")
async def admin_login_page(request: Request):
    """Show the admin login form."""
    from fastapi.responses import HTMLResponse

    if _needs_setup(request):
        return RedirectResponse(url=_SETUP_PATH, status_code=302)

    # Already logged in – redirect to dashboard
    if request.cookies.get(SESSION_COOKIE_NAME):
        return HTMLResponse(
            content=jinja_env.get_template("login.html").render(
                **_common_ctx(request, "Admin Login", flash="Already logged in."),
                redirect_to="/dashboard",
                error="",
            ),
            status_code=302,
        )

    return HTMLResponse(
        content=jinja_env.get_template("login.html").render(
            **_common_ctx(request, "Admin Login", flash=""),
            redirect_to="/dashboard",
            error="",
        ),
    )


@router.post("/login")
async def admin_login_submit(
    request: Request,
    email: str = Form(..., max_length=L.EMAIL_LEN),
    password: str = Form(..., max_length=L.PASSWORD_LEN),
    session=Depends(get_session),
):
    """Authenticate the admin and create a session cookie."""
    from fastapi.responses import HTMLResponse
    from models.user import User

    result = await session.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()

    if not user or not verify_password(password, user.password_hash):
        return HTMLResponse(
            content=jinja_env.get_template("login.html").render(
                **_common_ctx(request, "Admin Login", flash=""),
                redirect_to="/dashboard",
                error="Invalid email or password",
            ),
        )

    if not user.is_admin:
        return HTMLResponse(
            content=jinja_env.get_template("login.html").render(
                **_common_ctx(request, "Admin Login", flash=""),
                redirect_to="/dashboard",
                error="You do not have admin privileges",
            ),
        )

    if not user.is_active:
        return HTMLResponse(
            content=jinja_env.get_template("login.html").render(
                **_common_ctx(request, "Admin Login", flash=""),
                redirect_to="/dashboard",
                error="Account is deactivated",
            ),
        )

    resp = RedirectResponse(url="/admin/dashboard", status_code=302)
    set_session_cookie(resp, user.id)
    return resp


@router.get("/logout")
async def admin_logout(request: Request):
    """Destroy the session and redirect to the login page."""
    resp = RedirectResponse(url="/admin/login", status_code=302)
    clear_session_cookie(resp)
    return resp


# ------------------------------------------------------------------
# Dashboard
# ------------------------------------------------------------------

@router.get("/")
@router.get("/dashboard")
async def admin_dashboard(request: Request, db=Depends(require_admin_session)):
    """Admin dashboard with key metrics."""
    from models.order import Order
    from models.product import Product

    # Try to get stats; fall back gracefully if DB is unavailable
    stats: Dict[str, Any] = {
        "total_products": 0,
        "total_orders": 0,
        "total_revenue_cents": 0,
        "recent_orders": [],
        "pending_orders": 0,
    }

    if db is not None:
        from datetime import timedelta

        try:
            # Total products
            p_count = await db.execute(select(func.count(Product.id)))
            stats["total_products"] = p_count.scalar() or 0

            # Total orders
            o_count = await db.execute(select(func.count(Order.id)))
            stats["total_orders"] = o_count.scalar() or 0

            # Total revenue
            rev = await db.execute(select(func.coalesce(func.sum(Order.total_cents), 0)))
            stats["total_revenue_cents"] = rev.scalar() or 0

            # Pending orders count
            pending = await db.execute(select(func.count(Order.id)).where(col(Order.status) == "pending"))
            stats["pending_orders"] = pending.scalar() or 0

            # Recent orders (last 5)
            from models.order_item import OrderItem

            stmt = (
                select(Order, OrderItem.product_name, OrderItem.quantity)
                .join(OrderItem, Order.id == OrderItem.order_id, isouter=True)
                .order_by(col(Order.created_at).desc())
                .limit(5)
            )
            res = await db.execute(stmt)
            rows = res.all()
            for order, product_name, qty in rows:
                stats["recent_orders"].append(
                    {
                        "id": order.id,
                        "status": order.status,
                        "total_cents": order.total_cents,
                        "created_at": order.created_at,
                        "product_name": product_name or "—",
                        "quantity": qty or 0,
                    }
                )

        except Exception:
            pass  # DB unavailable during init, use defaults

    return _template(
        "dashboard.html",
        **_common_ctx(request, "Dashboard"),
        restart_flag_enabled=settings.addon_install_restart_flag_path is not None,
        restart_flag_path=settings.addon_install_restart_flag_file or "",
        **stats,
    )


# ------------------------------------------------------------------
# Products
# ------------------------------------------------------------------

@router.get("/products")
async def admin_products_list(
    request: Request,
    page: int = Query(1, ge=1),
    db=Depends(require_admin_session),
):
    """List products with pagination."""
    from models.product import Product
    from models.category import Category

    PAGE_SIZE = 20
    offset = (page - 1) * PAGE_SIZE

    stmt = (
        select(Product)
        .order_by(col(Product.created_at).desc())
        .offset(offset)
        .limit(PAGE_SIZE)
    )
    count_stmt = select(func.count(Product.id))

    total = 0
    items = []

    if db is not None:
        try:
            count_result = await db.execute(count_stmt)
            total = count_result.scalar() or 0

            result = await db.execute(stmt)
            items = result.scalars().all()
        except Exception:
            pass

    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)

    # Gather all categories for the dropdown (used on the form page too)
    categories = []
    if db is not None:
        try:
            cat_result = await db.execute(select(Category).order_by(col(Category.sort_order).asc()))
            categories = cat_result.scalars().all()
        except Exception:
            pass

    return _template(
        "products.html",
        **_common_ctx(request, "Products"),
        items=items,
        page=page,
        total=total,
        total_pages=total_pages,
        page_size=PAGE_SIZE,
        categories=categories,
    )


@router.get("/products/new")
async def admin_product_new(request: Request, db=Depends(require_admin_session)):
    """Show the create-product form."""
    categories = []
    if db is not None:
        try:
            from models.category import Category

            cat_result = await db.execute(select(Category).order_by(col(Category.sort_order).asc()))
            categories = cat_result.scalars().all()
        except Exception:
            pass

    return _template(
        "product_form.html",
        **_common_ctx(request, "New Product"),
        product=None,
        categories=categories,
    )


@router.post("/products")
async def admin_product_create(
    request: Request,
    name: str = Form(..., max_length=L.NAME_LEN),
    description: str = Form("", max_length=L.TEXT_LEN),
    price_cents: int = Form(ge=0, alias="price_cents"),
    compare_at_price_cents: Optional[int] = Form(None, ge=0, alias="compare_at_price_cents"),
    sku: Optional[str] = Form(None, max_length=L.SKU_LEN),
    inventory_quantity: int = Form(0, ge=0),
    status: str = Form("draft", max_length=32),
    category: Optional[str] = Form(None, max_length=L.NAME_LEN),
    tags: str = Form("[]", max_length=L.TAGS_JSON_LEN),
    csrf_token: str = Form(..., max_length=128),
    db=Depends(require_admin_session),
):
    """Create a new product."""
    from fastapi.responses import RedirectResponse
    from models.product import Product

    _require_csrf(request, csrf_token)

    try:
        parsed_tags = json.loads(tags) if tags else []
    except (json.JSONDecodeError, TypeError):
        parsed_tags = []

    if not db:
        return _render_error(request, "Database unavailable")

    product = Product(
        name=name,
        description=description or None,
        price_cents=price_cents,
        compare_at_price_cents=compare_at_price_cents,
        sku=sku or None,
        inventory_quantity=inventory_quantity,
        status=status,
        category=category or None,
        tags=parsed_tags,
        created_by=request.state.admin_user.id,
    )

    db.add(product)
    await db.commit()
    await db.refresh(product)

    from app.services.audit import log_change

    await log_change(
        db,
        actor_user_id=request.state.admin_user.id,
        action="create",
        resource_type="product",
        resource_id=product.id,
        ip_address=request.client.host if request.client else None,
    )
    await db.commit()

    resp = RedirectResponse(url="/admin/products", status_code=302)
    set_flash_cookie(resp, f"Product '{product.name}' created")
    return resp


@router.get("/products/{product_id}")
async def admin_product_edit(request: Request, product_id: int, db=Depends(require_admin_session)):
    """Show the edit-product form."""
    from models.product import Product
    from models.category import Category

    if not db:
        return _render_error(request, "Database unavailable")

    try:
        result = await db.execute(select(Product).where(Product.id == product_id))
        product = result.scalar_one_or_none()
    except Exception:
        return _render_error(request, "Database error")

    if not product:
        return _render_error(request, "Product not found", status_code=404)

    cat_result = await db.execute(select(Category).order_by(col(Category.sort_order).asc()))
    categories = cat_result.scalars().all()

    return _template(
        "product_form.html",
        **_common_ctx(request, f"Edit: {product.name}"),
        product=product,
        categories=categories,
    )


@router.post("/products/{product_id}")
async def admin_product_update(
    request: Request,
    product_id: int,
    name: str = Form(..., max_length=L.NAME_LEN),
    description: str = Form("", max_length=L.TEXT_LEN),
    price_cents: int = Form(ge=0, alias="price_cents"),
    compare_at_price_cents: Optional[int] = Form(None, ge=0, alias="compare_at_price_cents"),
    sku: Optional[str] = Form(None, max_length=L.SKU_LEN),
    inventory_quantity: int = Form(0, ge=0),
    status: str = Form("draft", max_length=32),
    category: Optional[str] = Form(None, max_length=L.NAME_LEN),
    tags: str = Form("[]", max_length=L.TAGS_JSON_LEN),
    csrf_token: str = Form(..., max_length=128),
    db=Depends(require_admin_session),
):
    """Update an existing product."""
    from fastapi.responses import RedirectResponse
    from models.product import Product

    _require_csrf(request, csrf_token)

    if not db:
        return _render_error(request, "Database unavailable")

    try:
        result = await db.execute(select(Product).where(Product.id == product_id))
        product = result.scalar_one_or_none()
    except Exception:
        return _render_error(request, "Database error")

    if not product:
        return _render_error(request, "Product not found", status_code=404)

    try:
        parsed_tags = json.loads(tags) if tags else []
    except (json.JSONDecodeError, TypeError):
        parsed_tags = []

    product.name = name
    product.description = description or None
    product.price_cents = price_cents
    product.compare_at_price_cents = compare_at_price_cents
    product.sku = sku or None
    product.inventory_quantity = inventory_quantity
    product.status = status
    product.category = category or None
    product.tags = parsed_tags
    product.updated_by = request.state.admin_user.id
    mark_instance_dirty(db, product)

    await db.commit()
    await db.refresh(product)

    from app.services.audit import log_change

    await log_change(
        db,
        actor_user_id=request.state.admin_user.id,
        action="update",
        resource_type="product",
        resource_id=product.id,
        ip_address=request.client.host if request.client else None,
    )
    await db.commit()

    resp = RedirectResponse(url="/admin/products", status_code=302)
    set_flash_cookie(resp, f"Product '{product.name}' updated")
    return resp


@router.post("/products/{product_id}/delete")
async def admin_product_delete(
    request: Request,
    product_id: int,
    csrf_token: str = Form(...),
    db=Depends(require_admin_session),
):
    """Delete a product."""
    from fastapi.responses import RedirectResponse
    from models.product import Product

    _require_csrf(request, csrf_token)

    if not db:
        return _render_error(request, "Database unavailable")

    try:
        result = await db.execute(select(Product).where(Product.id == product_id))
        product = result.scalar_one_or_none()
    except Exception:
        return _render_error(request, "Database error")

    if not product:
        return _render_error(request, "Product not found", status_code=404)

    product_name = product.name
    await db.delete(product)
    await db.commit()

    resp = RedirectResponse(url="/admin/products", status_code=302)
    set_flash_cookie(resp, f"Product '{product_name}' deleted")
    return resp


# ------------------------------------------------------------------
# Categories
# ------------------------------------------------------------------

@router.get("/categories")
async def admin_categories_list(
    request: Request,
    page: int = Query(1, ge=1),
    db=Depends(require_admin_session),
):
    """List categories with pagination."""
    from models.category import Category

    PAGE_SIZE = 25
    offset = (page - 1) * PAGE_SIZE
    categories = []
    total = 0

    if db is not None:
        try:
            count_result = await db.execute(select(func.count(Category.id)))
            total = count_result.scalar() or 0
            result = await db.execute(
                select(Category)
                .order_by(col(Category.sort_order).asc())
                .offset(offset)
                .limit(PAGE_SIZE)
            )
            categories = result.scalars().all()
        except Exception:
            pass

    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)

    return _template(
        "categories.html",
        **_common_ctx(request, "Categories"),
        categories=categories,
        page=page,
        total=total,
        total_pages=total_pages,
        page_size=PAGE_SIZE,
    )


@router.post("/categories")
async def admin_category_create(
    request: Request,
    name: str = Form(..., max_length=L.NAME_LEN),
    slug: str = Form(..., max_length=L.NAME_LEN),
    description: str = Form("", max_length=L.TEXT_LEN),
    parent_id: Optional[int] = Form(None),
    sort_order: int = Form(0),
    csrf_token: str = Form(..., max_length=128),
    db=Depends(require_admin_session),
):
    """Create a category."""
    from fastapi.responses import RedirectResponse
    from models.category import Category

    _require_csrf(request, csrf_token)

    if not db:
        return _render_error(request, "Database unavailable")

    cat = Category(
        name=name,
        slug=slug,
        description=description or None,
        parent_id=parent_id,
        sort_order=sort_order,
    )
    db.add(cat)
    await db.commit()
    await db.refresh(cat)

    resp = RedirectResponse(url="/admin/categories", status_code=302)
    set_flash_cookie(resp, f"Category '{cat.name}' created")
    return resp


# ------------------------------------------------------------------
# Orders
# ------------------------------------------------------------------

@router.get("/orders")
async def admin_orders_list(
    request: Request,
    page: int = Query(1, ge=1),
    status_filter: Optional[str] = Query(None),
    db=Depends(require_admin_session),
):
    """List orders with pagination and optional status filter."""
    from models.order import Order

    PAGE_SIZE = 20
    offset = (page - 1) * PAGE_SIZE

    stmt = select(Order).order_by(col(Order.created_at).desc()).offset(offset).limit(PAGE_SIZE)
    count_stmt = select(func.count(Order.id))

    if status_filter and status_filter != "all":
        stmt = stmt.where(col(Order.status) == status_filter)
        count_stmt = count_stmt.where(col(Order.status) == status_filter)

    total = 0
    items = []

    if db is not None:
        try:
            count_result = await db.execute(count_stmt)
            total = count_result.scalar() or 0

            result = await db.execute(stmt)
            items = result.scalars().all()
        except Exception:
            pass

    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)

    status_options = ["pending", "paid", "shipped", "delivered", "cancelled"]

    return _template(
        "orders.html",
        **_common_ctx(request, "Orders"),
        items=items,
        page=page,
        total=total,
        total_pages=total_pages,
        page_size=PAGE_SIZE,
        status_filter=status_filter,
        status_options=status_options,
    )


@router.get("/orders/{order_id}")
async def admin_order_detail(request: Request, order_id: int, db=Depends(require_admin_session)):
    """Show a single order with its line items."""
    from models.order import Order
    from models.order_item import OrderItem

    if not db:
        return _render_error(request, "Database unavailable")

    try:
        result = await db.execute(select(Order).where(Order.id == order_id))
        order = result.scalar_one_or_none()
    except Exception:
        return _render_error(request, "Database error")

    if not order:
        return _render_error(request, "Order not found", status_code=404)

    items_result = await db.execute(
        select(OrderItem).where(OrderItem.order_id == order_id).order_by(col(OrderItem.id).asc())
    )
    items = items_result.scalars().all()

    return _template(
        "order_detail.html",
        **_common_ctx(request, f"Order #{order.id}"),
        order=order,
        items=items,
        valid_statuses=["pending", "paid", "shipped", "delivered", "cancelled"],
    )


@router.post("/orders/{order_id}/status")
async def admin_order_update_status(
    request: Request,
    order_id: int,
    status: str = Form(...),
    csrf_token: str = Form(...),
    db=Depends(require_admin_session),
):
    """Update the status of an order."""
    from fastapi.responses import RedirectResponse
    from models.order import Order

    _require_csrf(request, csrf_token)

    valid = {"pending", "paid", "shipped", "delivered", "cancelled"}
    if status not in valid:
        return _render_error(request, f"Invalid status. Must be one of: {', '.join(sorted(valid))}")

    if not db:
        return _render_error(request, "Database unavailable")

    try:
        result = await db.execute(select(Order).where(Order.id == order_id))
        order = result.scalar_one_or_none()
    except Exception:
        return _render_error(request, "Database error")

    if not order:
        return _render_error(request, "Order not found", status_code=404)

    old_status = order.status
    from app.services.commerce import apply_order_status_change

    await apply_order_status_change(db, order, status)

    resp = RedirectResponse(url=f"/admin/orders/{order.id}", status_code=302)
    set_flash_cookie(
        resp,
        f"Order #{order.id} status changed from '{old_status}' to '{status}'",
    )
    return resp


# ------------------------------------------------------------------
# Site settings
# ------------------------------------------------------------------

@router.get("/settings")
async def admin_site_settings(request: Request, db=Depends(require_admin_session)):
    """Edit site-wide branding and contact settings."""
    from app.services.site_settings import get_site_settings

    site = await get_site_settings(db)
    return _template(
        "site_settings.html",
        **_common_ctx(request, "Site Settings"),
        site=site,
    )


@router.post("/settings")
async def admin_site_settings_save(
    request: Request,
    store_name: str = Form(..., max_length=L.NAME_LEN),
    logo_url: str = Form("", max_length=L.URL_LEN),
    favicon_url: str = Form("", max_length=L.URL_LEN),
    primary_color: str = Form("#2563eb", max_length=L.COLOR_LEN),
    secondary_color: str = Form("#64748b", max_length=L.COLOR_LEN),
    font_family: str = Form("system-ui, sans-serif", max_length=L.NAME_LEN),
    support_email: str = Form("", max_length=L.EMAIL_LEN),
    meta_description: str = Form("", max_length=L.TEXT_LEN),
    csrf_token: str = Form(..., max_length=128),
    db=Depends(require_admin_session),
):
    """Save site-wide settings."""
    from app.services.site_settings import get_site_settings, update_site_settings

    _require_csrf(request, csrf_token)

    try:
        await update_site_settings(
            db,
            {
                "store_name": store_name,
                "logo_url": logo_url,
                "favicon_url": favicon_url,
                "primary_color": primary_color,
                "secondary_color": secondary_color,
                "font_family": font_family,
                "support_email": support_email,
                "meta_description": meta_description,
            },
        )
        await db.commit()
        request.state.site_settings = await get_site_settings(db)
        resp = RedirectResponse(url="/admin/settings", status_code=302)
        set_flash_cookie(resp, "Site settings saved")
        return resp
    except Exception as exc:
        return _render_error(request, f"Failed to save settings: {exc}")


# ------------------------------------------------------------------
# Addons (by category)
# ------------------------------------------------------------------

_ADDON_CATEGORY_PAGES: dict[str, dict[str, str]] = {
    "supplier": {
        "nav_section": "suppliers",
        "list_path": "/admin/suppliers",
        "title": "Suppliers",
        "description": "Manage fulfillment and inventory supplier integrations.",
    },
    "payment": {
        "nav_section": "payments",
        "list_path": "/admin/payments",
        "title": "Payments",
        "description": "Manage payment processors and checkout configuration.",
    },
    "frontend": {
        "nav_section": "frontends",
        "list_path": "/admin/frontends",
        "title": "Frontends",
        "description": "Manage storefront themes and SPA frontends.",
    },
    "tool": {
        "nav_section": "tools",
        "list_path": "/admin/tools",
        "title": "Tools",
        "description": "Advanced shop utilities: analytics, A/B testing, and other optional integrations.",
    },
}


def _addon_nav_section(category: str) -> str | None:
    meta = _ADDON_CATEGORY_PAGES.get(category)
    return meta["nav_section"] if meta else None


def _addon_list_path(category: str) -> str:
    meta = _ADDON_CATEGORY_PAGES.get(category)
    return meta["list_path"] if meta else "/admin/suppliers"


async def _admin_addon_category_list(
    request: Request, db: AsyncSession | None, category: str
):
    """List addons for a single category."""
    from models.addon_config import AddonConfig
    from app.services.addons import merge_addon_list

    page = _ADDON_CATEGORY_PAGES[category]
    stored: dict = {}
    if db is not None:
        try:
            result = await db.execute(select(AddonConfig))
            for row in result.scalars().all():
                stored[row.addon_id] = row
        except Exception:
            pass

    addons = [
        a for a in merge_addon_list(stored) if a["addon_category"] == category
    ]

    return _template(
        "addons.html",
        **_common_ctx(request, page["title"]),
        addons=addons,
        page_heading=page["title"],
        page_description=page["description"],
        nav_section=page["nav_section"],
    )


@router.get("/suppliers")
async def admin_suppliers_list(request: Request, db=Depends(require_admin_session)):
    return await _admin_addon_category_list(request, db, "supplier")


@router.get("/payments")
async def admin_payments_list(request: Request, db=Depends(require_admin_session)):
    return await _admin_addon_category_list(request, db, "payment")


@router.get("/frontends")
async def admin_frontends_list(request: Request, db=Depends(require_admin_session)):
    return await _admin_addon_category_list(request, db, "frontend")


@router.get("/tools")
async def admin_tools_list(request: Request, db=Depends(require_admin_session)):
    return await _admin_addon_category_list(request, db, "tool")


@router.get("/addons")
async def admin_addons_list(request: Request, db=Depends(require_admin_session)):
    """Legacy URL — redirect to suppliers list."""
    return RedirectResponse(url="/admin/suppliers", status_code=302)


def _addon_install_success_message(result) -> str:
    from app.services.addon_install import AddonInstallResult

    assert isinstance(result, AddonInstallResult)
    msg = (
        f"{result.addon_name} (v{result.version}) installed. "
        "Restart the server to load the new addon."
    )
    if result.restart_flag_written and result.restart_flag_path:
        msg += f" A restart flag was written to {result.restart_flag_path}."
    return msg


def _addon_install_error_redirect(request: Request, message: str) -> RedirectResponse:
    resp = RedirectResponse(url="/admin/dashboard", status_code=302)
    set_flash_cookie(resp, message)
    return resp


@router.post("/addons/install")
async def admin_addon_install_zip(
    request: Request,
    archive: UploadFile = File(...),
    force: str = Form("off", max_length=8),
    csrf_token: str = Form(..., max_length=128),
    db=Depends(require_admin_session),
):
    """Install an addon from an uploaded ZIP archive."""
    from app.core.exceptions import ValidationError
    from app.services.addon_install import install_addon_archive, read_limited_stream

    _require_csrf(request, csrf_token)

    if not archive.filename or not archive.filename.lower().endswith(".zip"):
        return _addon_install_error_redirect(request, "Upload must be a .zip file")

    try:
        data = read_limited_stream(archive.file, settings.addon_install_max_bytes)
        result = install_addon_archive(data, force=force == "on")
    except ValidationError as exc:
        return _addon_install_error_redirect(request, exc.message)
    except Exception as exc:
        return _addon_install_error_redirect(request, f"Install failed: {exc}")

    redirect_url = _addon_list_path(result.category)
    resp = RedirectResponse(url=redirect_url, status_code=302)
    set_flash_cookie(resp, _addon_install_success_message(result))
    return resp


@router.post("/addons/install/url")
async def admin_addon_install_url(
    request: Request,
    url: str = Form(..., max_length=L.ADDON_INSTALL_URL_LEN),
    force: str = Form("off", max_length=8),
    csrf_token: str = Form(..., max_length=128),
    db=Depends(require_admin_session),
):
    """Install an addon downloaded from an HTTPS URL."""
    from app.core.exceptions import ValidationError
    from app.services.addon_install import install_addon_from_url

    _require_csrf(request, csrf_token)

    try:
        result = await install_addon_from_url(url.strip(), force=force == "on")
    except ValidationError as exc:
        return _addon_install_error_redirect(request, exc.message)
    except Exception as exc:
        return _addon_install_error_redirect(request, f"Install failed: {exc}")

    redirect_url = _addon_list_path(result.category)
    resp = RedirectResponse(url=redirect_url, status_code=302)
    set_flash_cookie(resp, _addon_install_success_message(result))
    return resp


@router.get("/addons/{addon_id}/configure")
async def admin_addon_configure(
    request: Request, addon_id: str, db=Depends(require_admin_session)
):
    """Show generic JSON configuration for addons without dedicated admin UI."""
    from app.addons.registry import addon_registry
    from models.addon_config import AddonConfig

    addon = addon_registry.get(addon_id)
    if addon is None:
        return _render_error(request, f"Unknown addon: {addon_id}", status_code=404)

    if addon.get_admin_routes():
        from fastapi.responses import RedirectResponse

        return RedirectResponse(url=addon._configure_url(), status_code=302)

    stored_addon: Optional[AddonConfig] = None
    if db is not None:
        try:
            result = await db.execute(
                select(AddonConfig).where(AddonConfig.addon_id == addon_id)
            )
            stored_addon = result.scalar_one_or_none()
        except Exception:
            pass

    config = stored_addon.config if stored_addon else addon_registry.get_config(addon_id)
    config_json = json.dumps(config, indent=2)

    list_path = _addon_list_path(addon.addon_category)
    return _template(
        "addon_config.html",
        **_common_ctx(request, f"Configure: {addon.addon_name}"),
        addon_name=addon.addon_name,
        addon_id=addon_id,
        config_json=config_json,
        is_enabled=stored_addon.is_enabled if stored_addon else addon.is_enabled,
        list_path=list_path,
        list_label=_ADDON_CATEGORY_PAGES.get(addon.addon_category, {}).get(
            "title", "Addons"
        ),
        nav_section=_addon_nav_section(addon.addon_category),
    )


@router.post("/addons/{addon_id}/configure")
async def admin_addon_save_config(
    request: Request,
    addon_id: str,
    is_enabled: str = Form("off", max_length=8),
    config: str = Form("{}", max_length=L.CONFIG_JSON_LEN),
    csrf_token: str = Form(..., max_length=128),
    db=Depends(require_admin_session),
):
    """Save generic JSON configuration for an addon."""
    from fastapi.responses import RedirectResponse
    from app.addons.registry import addon_registry
    from app.services.addons import persist_addon_config

    _require_csrf(request, csrf_token)

    if addon_registry.get(addon_id) is None:
        return _render_error(request, f"Unknown addon: {addon_id}", status_code=404)

    try:
        config_data = json.loads(config)
    except (json.JSONDecodeError, TypeError):
        return _render_error(request, "Invalid JSON in config")

    enabled = is_enabled == "on"

    if not db:
        return _render_error(request, "Database unavailable")

    try:
        addon = addon_registry.get(addon_id)
        await persist_addon_config(db, addon_id, config_data, enabled)
        await db.commit()

        list_url = _addon_list_path(addon.addon_category) if addon else "/admin/suppliers"
        resp = RedirectResponse(url=list_url, status_code=302)
        set_flash_cookie(
            resp,
            f"{addon.addon_name if addon else addon_id} configuration saved",
        )
        return resp

    except Exception as exc:
        return _render_error(request, f"Failed to save config: {exc}")


# ------------------------------------------------------------------
# Audit log
# ------------------------------------------------------------------

@router.get("/audit")
async def admin_audit_list(
    request: Request,
    page: int = Query(1, ge=1),
    db=Depends(require_admin_session),
):
    """Read-only audit trail."""
    from models.audit_log import AuditLog

    PAGE_SIZE = 25
    offset = (page - 1) * PAGE_SIZE
    entries: list[AuditLog] = []
    total = 0

    if db is not None:
        try:
            count_result = await db.execute(select(func.count(AuditLog.id)))
            total = count_result.scalar() or 0
            result = await db.execute(
                select(AuditLog)
                .order_by(col(AuditLog.created_at).desc())
                .offset(offset)
                .limit(PAGE_SIZE)
            )
            entries = list(result.scalars().all())
        except Exception:
            pass

    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)

    return _template(
        "audit.html",
        **_common_ctx(request, "Audit Log"),
        entries=entries,
        page=page,
        total=total,
        total_pages=total_pages,
        page_size=PAGE_SIZE,
    )


# ------------------------------------------------------------------
# Error page (404 for admin-specific not-found)
# ------------------------------------------------------------------

@router.get("/error")
async def admin_error_page(request: Request, message: str = "An error occurred"):
    """Render the generic admin error page."""
    return _render_error(request, message)


# ------------------------------------------------------------------
# Static file serving
# ------------------------------------------------------------------

from fastapi.responses import FileResponse

from starlette.requests import Request as StarletteRequest


@router.get("/static/{path:path}")
async def admin_static(path: str):
    """Serve admin static files (CSS, JS, images)."""
    file_path = STATIC_DIR / path
    if file_path.exists() and file_path.is_file():
        return FileResponse(str(file_path))
    return FileResponse(str(STATIC_DIR / "404.png"), status_code=404)
