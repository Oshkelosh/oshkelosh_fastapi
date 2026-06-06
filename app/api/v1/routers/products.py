"""Product endpoints.

Provides public listing, individual product retrieval, and admin CRUD
operations for the product catalogue.
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlmodel import col, func, select

from app.core.dependencies import CurrentUser, get_admin_user, get_current_user
from app.core.exceptions import NotFound, ValidationError
from app.db.connection import get_session, mark_instance_dirty
from models.category import Category
from models.product import Product
from models.product_image import ProductImage
from schemas.product import (
    ProductCreate,
    ProductImageCreate,
    ProductRead,
    ProductUpdate,
)

router = APIRouter(prefix="/products", tags=["products"])

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------
# Sort mapping
# ------------------------------------------------------------------

SUPPORTED_SORT_FIELDS = {
    "name", "price_cents", "created_at", "updated_at",
}
SUPPORTED_SORT_DIRECTIONS = {"asc", "desc"}


# ------------------------------------------------------------------
# Public endpoints
# ------------------------------------------------------------------

@router.get(
    "",
    response_model=dict,
    summary="List products",
    description=(
        "Return a paginated list of published products. Supports filtering "
        "by category, search (name/description), status, and sorting."
    ),
)
async def list_products(
    page: int = Query(default=1, ge=1, description="Page number"),
    page_size: int = Query(default=20, ge=1, le=100, description="Items per page"),
    category: Optional[str] = Query(default=None, description="Filter by category slug"),
    status: Optional[str] = Query(default=None, description="Filter by status (draft|published|archived)"),
    search: Optional[str] = Query(default=None, description="Search name or description"),
    sort: str = Query(default="created_at", description="Sort field"),
    order: str = Query(default="desc", description="Sort direction (asc|desc)"),
    session=Depends(get_session),
) -> dict:
    """List published products with filtering, search, and sorting."""
    if sort not in SUPPORTED_SORT_FIELDS:
        sort = "created_at"
    if order not in SUPPORTED_SORT_DIRECTIONS:
        order = "desc"

    if status is not None and status != "published":
        raise ValidationError(
            message="Public catalog only lists published products; omit status or use published"
        )

    stmt = select(Product).where(col(Product.status) == "published")

    if category:
        stmt = stmt.where(col(Product.category) == category)

    if search:
        search_pattern = f"%{search}%"
        stmt = stmt.where(
            col(Product.name).ilike(search_pattern)
            | col(Product.description).ilike(search_pattern)
        )

    sort_col = getattr(Product, sort, Product.created_at)
    if order == "desc":
        stmt = stmt.order_by(sort_col.desc())
    else:
        stmt = stmt.order_by(sort_col.asc())

    total = await session.execute(select(func.count()).select_from(stmt.subquery()))
    total_count: int = total.scalar_one()

    offset = (page - 1) * page_size
    stmt = stmt.offset(offset).limit(page_size)
    result = await session.execute(stmt)
    products = result.scalars().all()

    total_pages = max(1, (total_count + page_size - 1) // page_size)

    return {
        "items": [ProductRead.model_validate(p).model_dump() for p in products],
        "total": total_count,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
    }


@router.get(
    "/{product_id}",
    response_model=ProductRead,
    summary="Get product detail",
    description="Return the full detail of a single published product.",
)
async def get_product(
    product_id: int,
    session=Depends(get_session),
) -> ProductRead:
    """Return a single product's detail."""
    product = await session.get(Product, product_id)
    if product is None or product.status != "published":
        raise NotFound(resource_name="Product", resource_id=product_id)
    return ProductRead.model_validate(product)


@router.get(
    "/{product_id}/images",
    response_model=list[dict],
    summary="List product images",
    description="Return all images associated with a product.",
)
async def list_product_images(
    product_id: int,
    session=Depends(get_session),
) -> list[ProductImage]:
    """List all images for a given product."""
    product = await session.get(Product, product_id)
    if product is None or product.status != "published":
        raise NotFound(resource_name="Product", resource_id=product_id)

    result = await session.execute(
        select(ProductImage)
        .where(col(ProductImage.product_id) == product_id)
        .order_by(ProductImage.sort_order.asc())
    )
    return result.scalars().all()


@router.post(
    "/{product_id}/images",
    response_model=ProductImage,
    status_code=status.HTTP_201_CREATED,
    summary="Add product image",
    description="Attach a new image to a product.",
)
async def add_product_image(
    product_id: int,
    body: ProductImageCreate,
    current_user: CurrentUser = Depends(get_admin_user),
    session=Depends(get_session),
) -> ProductImage:
    """Add an image to a product (admin only)."""
    product = await session.get(Product, product_id)
    if product is None:
        raise NotFound(resource_name="Product", resource_id=product_id)

    image = ProductImage(
        product_id=product_id,
        url=body.url,
        alt_text=body.alt_text,
        sort_order=body.sort_order,
    )
    session.add(image)
    await session.flush()
    await session.refresh(image)
    return image


# ------------------------------------------------------------------
# Admin endpoints
# ------------------------------------------------------------------

@router.post(
    "",
    response_model=ProductRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create product",
    description="Create a new product (admin only).",
)
async def create_product(
    body: ProductCreate,
    current_user: CurrentUser = Depends(get_admin_user),
    session=Depends(get_session),
) -> Product:
    """Create a new product."""
    product = Product(
        name=body.name,
        description=body.description,
        price_cents=body.price_cents,
        compare_at_price_cents=body.compare_at_price_cents,
        sku=body.sku,
        inventory_quantity=body.inventory_quantity,
        status=body.status,
        category=body.category,
        tags=body.tags or [],
        images=body.images or [],
        created_by=current_user.id,
    )
    session.add(product)
    await session.flush()
    await session.refresh(product)
    return product


@router.patch(
    "/{product_id}",
    response_model=ProductRead,
    summary="Update product",
    description="Update an existing product (admin only). Only provided fields are updated.",
)
async def update_product(
    product_id: int,
    body: ProductUpdate,
    current_user: CurrentUser = Depends(get_admin_user),
    session=Depends(get_session),
) -> Product:
    """Update an existing product."""
    product = await session.get(Product, product_id)
    if product is None:
        raise NotFound(resource_name="Product", resource_id=product_id)

    update_data = body.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(product, key, value)
    mark_instance_dirty(session, product)

    await session.flush()
    await session.refresh(product)
    return product


@router.delete(
    "/{product_id}",
    response_model=dict,
    summary="Delete product",
    description="Delete a product (admin only).",
)
async def delete_product(
    product_id: int,
    current_user: CurrentUser = Depends(get_admin_user),
    session=Depends(get_session),
) -> dict:
    """Delete a product."""
    product = await session.get(Product, product_id)
    if product is None:
        raise NotFound(resource_name="Product", resource_id=product_id)

    await session.delete(product)
    return {"message": f"Product {product_id} deleted"}
