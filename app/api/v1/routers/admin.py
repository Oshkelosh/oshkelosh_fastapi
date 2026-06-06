"""Admin API endpoints."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlmodel import col, func, select

from app.api.v1.routers.orders import VALID_TRANSITIONS
from app.core.dependencies import CurrentUser, get_admin_user
from app.core.exceptions import NotFound, ValidationError
from app.db.connection import get_session, mark_instance_dirty
from models.addon_config import AddonConfig
from models.category import Category
from models.order import Order
from models.product import Product
from models.user import User
from schemas.base import PaginatedResponse
from schemas.category import CategoryCreate, CategoryRead, CategoryUpdate
from schemas.order import OrderRead, OrderUpdateStatus
from schemas.product import ProductCreate, ProductRead, ProductUpdate

router = APIRouter(prefix="/admin", tags=["admin"])


class DashboardStats(BaseModel):
    total_products: int
    total_orders: int
    total_revenue_cents: int
    pending_orders: int
    total_users: int


async def _paginate(session, stmt, page: int, page_size: int):
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total_result = await session.execute(count_stmt)
    total = total_result.scalar_one() or 0
    offset = (page - 1) * page_size
    items_result = await session.execute(stmt.offset(offset).limit(page_size))
    items = items_result.scalars().all()
    return PaginatedResponse(
        items=list(items),
        page=page,
        page_size=page_size,
        total=total,
    )


@router.get("/stats", response_model=DashboardStats)
async def get_dashboard_stats(
    session=Depends(get_session),
    current_user: CurrentUser = Depends(get_admin_user),
) -> DashboardStats:
    """Return admin dashboard statistics."""
    total_products = (
        await session.execute(select(func.count()).select_from(Product))
    ).scalar_one()
    total_orders = (
        await session.execute(select(func.count()).select_from(Order))
    ).scalar_one()
    total_revenue = (
        await session.execute(
            select(func.coalesce(func.sum(Order.total_cents), 0)).where(
                col(Order.status) == "paid"
            )
        )
    ).scalar_one()
    pending_orders = (
        await session.execute(
            select(func.count()).select_from(Order).where(col(Order.status) == "pending")
        )
    ).scalar_one()
    total_users = (
        await session.execute(select(func.count()).select_from(User))
    ).scalar_one()
    return DashboardStats(
        total_products=total_products or 0,
        total_orders=total_orders or 0,
        total_revenue_cents=total_revenue or 0,
        pending_orders=pending_orders or 0,
        total_users=total_users or 0,
    )


@router.get("/products", response_model=PaginatedResponse[ProductRead])
async def admin_list_products(
    session=Depends(get_session),
    current_user: CurrentUser = Depends(get_admin_user),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: str | None = Query(None),
    search: str | None = Query(None),
):
    """List all products (admin)."""
    stmt = select(Product).order_by(col(Product.created_at).desc())
    if status:
        stmt = stmt.where(col(Product.status) == status)
    if search:
        pattern = f"%{search}%"
        stmt = stmt.where(
            col(Product.name).ilike(pattern) | col(Product.description).ilike(pattern)
        )
    return await _paginate(session, stmt, page, page_size)


@router.post("/products", response_model=ProductRead, status_code=201)
async def admin_create_product(
    data: ProductCreate,
    session=Depends(get_session),
    current_user: CurrentUser = Depends(get_admin_user),
) -> Product:
    """Create a new product."""
    product = Product(
        **data.model_dump(exclude={"created_by"}),
        created_by=current_user.id,
    )
    session.add(product)
    await session.flush()
    await session.refresh(product)
    return product


@router.patch("/products/{product_id}", response_model=ProductRead)
async def admin_update_product(
    product_id: int,
    data: ProductUpdate,
    session=Depends(get_session),
    current_user: CurrentUser = Depends(get_admin_user),
) -> Product:
    """Update a product."""
    product = await session.get(Product, product_id)
    if not product:
        raise NotFound(resource_name="Product", resource_id=product_id)
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(product, key, value)
    mark_instance_dirty(session, product)
    await session.flush()
    await session.refresh(product)
    return product


@router.delete("/products/{product_id}", status_code=204)
async def admin_delete_product(
    product_id: int,
    session=Depends(get_session),
    current_user: CurrentUser = Depends(get_admin_user),
) -> None:
    """Delete a product."""
    product = await session.get(Product, product_id)
    if not product:
        raise NotFound(resource_name="Product", resource_id=product_id)
    await session.delete(product)


@router.get("/categories", response_model=PaginatedResponse[CategoryRead])
async def admin_list_categories(
    session=Depends(get_session),
    current_user: CurrentUser = Depends(get_admin_user),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    """List all categories."""
    stmt = select(Category).order_by(col(Category.sort_order))
    return await _paginate(session, stmt, page, page_size)


@router.post("/categories", response_model=CategoryRead, status_code=201)
async def admin_create_category(
    data: CategoryCreate,
    session=Depends(get_session),
    current_user: CurrentUser = Depends(get_admin_user),
) -> Category:
    """Create a category."""
    cat = Category(**data.model_dump())
    session.add(cat)
    await session.flush()
    await session.refresh(cat)
    return cat


@router.patch("/categories/{slug}", response_model=CategoryRead)
async def admin_update_category(
    slug: str,
    data: CategoryUpdate,
    session=Depends(get_session),
    current_user: CurrentUser = Depends(get_admin_user),
) -> Category:
    """Update a category."""
    result = await session.execute(select(Category).where(col(Category.slug) == slug))
    cat = result.scalar_one_or_none()
    if not cat:
        raise NotFound(resource_name="Category", resource_id=slug)
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(cat, key, value)
    mark_instance_dirty(session, cat)
    await session.flush()
    await session.refresh(cat)
    return cat


@router.delete("/categories/{slug}", status_code=204)
async def admin_delete_category(
    slug: str,
    session=Depends(get_session),
    current_user: CurrentUser = Depends(get_admin_user),
) -> None:
    """Delete a category."""
    result = await session.execute(select(Category).where(col(Category.slug) == slug))
    cat = result.scalar_one_or_none()
    if not cat:
        raise NotFound(resource_name="Category", resource_id=slug)
    await session.delete(cat)


@router.get("/orders", response_model=PaginatedResponse[OrderRead])
async def admin_list_orders(
    session=Depends(get_session),
    current_user: CurrentUser = Depends(get_admin_user),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: str | None = Query(None),
):
    """List all orders (admin)."""
    stmt = select(Order).order_by(col(Order.created_at).desc())
    if status:
        stmt = stmt.where(col(Order.status) == status)
    return await _paginate(session, stmt, page, page_size)


@router.patch("/orders/{order_id}/status", response_model=OrderRead)
async def admin_update_order_status(
    order_id: int,
    data: OrderUpdateStatus,
    session=Depends(get_session),
    current_user: CurrentUser = Depends(get_admin_user),
) -> Order:
    """Update an order's status."""
    from app.services.commerce import apply_order_status_change, serialize_order

    order = await session.get(Order, order_id)
    if not order:
        raise NotFound(resource_name="Order", resource_id=order_id)

    allowed = VALID_TRANSITIONS.get(order.status, set())
    if data.status not in allowed:
        raise ValidationError(
            message=f"Cannot transition from '{order.status}' to '{data.status}'"
        )

    await apply_order_status_change(session, order, data.status)
    await session.flush()
    return await serialize_order(session, order)


@router.get("/addons")
async def admin_list_addons(
    session=Depends(get_session),
    current_user: CurrentUser = Depends(get_admin_user),
):
    """List all discovered addons merged with persisted configuration."""
    from app.services.addons import merge_addon_list

    result = await session.execute(select(AddonConfig))
    stored = {row.addon_id: row for row in result.scalars().all()}
    return merge_addon_list(stored)


@router.put("/addons/{addon_id}")
async def admin_configure_addon(
    addon_id: str,
    data: dict,
    session=Depends(get_session),
    current_user: CurrentUser = Depends(get_admin_user),
):
    """Enable/disable and configure an addon."""
    from app.services.addons import persist_addon_config

    row = await persist_addon_config(
        session,
        addon_id,
        data.get("config", {}),
        data.get("is_enabled", False),
    )
    await session.flush()
    await session.refresh(row)
    return {
        "id": row.id,
        "addon_id": row.addon_id,
        "addon_type": row.addon_type,
        "is_enabled": row.is_enabled,
        "config": row.config,
        "updated_at": row.updated_at,
    }
