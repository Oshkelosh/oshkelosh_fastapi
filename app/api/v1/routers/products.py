"""Product endpoints.

Provides public listing, individual product retrieval, and admin CRUD
operations for the product catalogue.
"""

import hashlib
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlmodel import col, func, select

from app.core.dependencies import CurrentUser, get_admin_user, get_current_user
from app.core.exceptions import NotFound, ValidationError
from app.db.connection import get_session, mark_instance_dirty
from app.services.product_defaults import apply_product_creation_defaults, validate_api_product_update
from app.services.categories import resolve_category_id
from app.services.product_slugs import ensure_product_slug, sku_exists, slug_exists
from app.services.site_settings import get_site_settings
from models.category import Category
from models.product import Product
from models.product_image import ProductImage
from app.services.product_images import build_product_detail_read, build_product_read, build_product_reads
from app.services.product_variants import create_default_variant
from app.services.product_popularity import popularity_order_clause
from app.services.product_search import apply_core_search_filter, search_products as delegate_product_search
from schemas.product import (
    ProductCreate,
    ProductDetailRead,
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
    "name", "price_cents", "created_at", "updated_at", "units_sold", "popularity",
}
SUPPORTED_SORT_DIRECTIONS = {"asc", "desc"}

_LIST_CACHE_DEFAULT = "public, max-age=60, stale-while-revalidate=300"
_LIST_CACHE_POPULARITY = "public, max-age=30"
_DETAIL_CACHE = "public, max-age=300"


def _set_list_cache_headers(response: Response, sort: str) -> None:
    if sort == "popularity":
        response.headers["Cache-Control"] = _LIST_CACHE_POPULARITY
    else:
        response.headers["Cache-Control"] = _LIST_CACHE_DEFAULT


def _set_detail_cache_headers(response: Response, product: Product) -> None:
    response.headers["Cache-Control"] = _DETAIL_CACHE
    etag_source = f"{product.id}:{product.updated_at}:{product.units_sold}"
    response.headers["ETag"] = (
        f'W/"{hashlib.sha256(etag_source.encode()).hexdigest()[:16]}"'
    )


def _apply_product_sort(stmt, sort: str, order: str):
    if sort == "popularity":
        return stmt.order_by(popularity_order_clause(order))
    sort_col = getattr(Product, sort, Product.created_at)
    if order == "desc":
        return stmt.order_by(sort_col.desc())
    return stmt.order_by(sort_col.asc())


async def _resolve_list_category_id(
    session,
    *,
    category_id: Optional[int],
    category: Optional[str],
) -> Optional[int]:
    """Resolve category_id from explicit id or category slug for product listing."""
    if category_id is not None:
        return category_id
    if not category or not category.strip():
        return None
    result = await session.execute(
        select(Category.id).where(col(Category.slug) == category.strip())
    )
    resolved = result.scalar_one_or_none()
    if resolved is None:
        return -1
    return resolved


# ------------------------------------------------------------------
# Public endpoints
# ------------------------------------------------------------------

@router.get(
    "",
    response_model=dict,
    summary="List products",
    description=(
        "Return a paginated list of published products. Supports filtering "
        "by category_id or category slug, search (name/description), status, and sorting."
    ),
)
async def list_products(
    response: Response,
    page: int = Query(default=1, ge=1, description="Page number"),
    page_size: int = Query(default=20, ge=1, le=100, description="Items per page"),
    category_id: Optional[int] = Query(default=None, description="Filter by category id"),
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

    resolved_category_id = await _resolve_list_category_id(
        session,
        category_id=category_id,
        category=category,
    )

    stmt = select(Product).where(col(Product.status) == "published")

    if resolved_category_id is not None:
        stmt = stmt.where(col(Product.category_id) == resolved_category_id)

    if search:
        delegated = await delegate_product_search(
            session,
            stmt,
            search,
            page=page,
            page_size=page_size,
            category_id=resolved_category_id,
            sort=sort,
            order=order,
        )
        if delegated is not None:
            _set_list_cache_headers(response, sort)
            return delegated
        stmt = apply_core_search_filter(stmt, search)

    stmt = _apply_product_sort(stmt, sort, order)

    total = await session.execute(select(func.count()).select_from(stmt.subquery()))
    total_count: int = total.scalar_one()

    offset = (page - 1) * page_size
    stmt = stmt.offset(offset).limit(page_size)
    result = await session.execute(stmt)
    products = result.scalars().all()

    total_pages = max(1, (total_count + page_size - 1) // page_size)

    product_reads = await build_product_reads(session, list(products))

    _set_list_cache_headers(response, sort)

    return {
        "items": [product_read.model_dump() for product_read in product_reads],
        "total": total_count,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
    }


@router.get(
    "/by-slug/{slug}",
    response_model=ProductDetailRead,
    summary="Get product by slug",
    description="Return the full detail of a single published product by URL slug.",
)
async def get_product_by_slug(
    slug: str,
    response: Response,
    session=Depends(get_session),
) -> ProductDetailRead:
    """Return a single published product by slug."""
    result = await session.execute(
        select(Product).where(col(Product.slug) == slug, col(Product.status) == "published")
    )
    product = result.scalar_one_or_none()
    if product is None:
        raise NotFound(resource_name="Product", resource_id=slug)
    _set_detail_cache_headers(response, product)
    return await build_product_detail_read(session, product)


@router.get(
    "/{product_id}",
    response_model=ProductDetailRead,
    summary="Get product detail",
    description="Return the full detail of a single published product.",
)
async def get_product(
    product_id: int,
    response: Response,
    session=Depends(get_session),
) -> ProductDetailRead:
    """Return a single product's detail."""
    result = await session.execute(
        select(Product).where(col(Product.id) == product_id)
    )
    product = result.scalar_one_or_none()
    if product is None or product.status != "published":
        raise NotFound(resource_name="Product", resource_id=product_id)
    _set_detail_cache_headers(response, product)
    return await build_product_detail_read(session, product)


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
) -> ProductRead:
    """Create a new product."""
    if body.slug and await slug_exists(session, body.slug):
        raise ValidationError(message=f"Product with slug '{body.slug}' already exists")
    if body.sku and await sku_exists(session, body.sku):
        raise ValidationError(message=f"Product with SKU '{body.sku}' already exists")

    category_id = await resolve_category_id(session, body.category_id)

    product = Product(
        name=body.name,
        description=body.description,
        price_cents=body.price_cents,
        compare_at_price_cents=body.compare_at_price_cents,
        sku=body.sku,
        inventory_quantity=body.inventory_quantity,
        status=body.status,
        category_id=category_id,
        options=body.options or {},
        tags=body.tags or [],
        meta_title=body.meta_title or None,
        meta_description=body.meta_description or None,
        created_by=current_user.id,
    )
    session.add(product)
    await session.flush()
    site_settings = await get_site_settings(session)
    store_name = site_settings.store_name or "Store"
    await apply_product_creation_defaults(
        session,
        product,
        store_name=store_name,
        preferred_slug=body.slug,
    )
    await create_default_variant(session, product)
    mark_instance_dirty(session, product)
    await session.flush()
    await session.refresh(product)
    return await build_product_read(session, product)


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
) -> ProductRead:
    """Update an existing product."""
    product = await session.get(Product, product_id)
    if product is None:
        raise NotFound(resource_name="Product", resource_id=product_id)

    update_data = body.model_dump(exclude_unset=True)
    preferred_slug = update_data.pop("slug", None)
    validate_api_product_update(product, update_data)
    if preferred_slug and await slug_exists(session, preferred_slug, exclude_id=product_id):
        raise ValidationError(message=f"Product with slug '{preferred_slug}' already exists")

    if "category_id" in update_data:
        update_data["category_id"] = await resolve_category_id(session, update_data["category_id"])

    for key, value in update_data.items():
        setattr(product, key, value)

    if preferred_slug:
        await ensure_product_slug(session, product, preferred=preferred_slug)
    mark_instance_dirty(session, product)

    await session.flush()
    await session.refresh(product)
    return await build_product_read(session, product)


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
    from app.services.product_slugs import product_has_order_items

    del current_user
    product = await session.get(Product, product_id)
    if product is None:
        raise NotFound(resource_name="Product", resource_id=product_id)
    if await product_has_order_items(session, product_id):
        raise ValidationError(
            message=f"Cannot delete product '{product.name}': it appears on existing orders"
        )

    await session.delete(product)
    return {"message": f"Product {product_id} deleted"}
