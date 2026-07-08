"""Product slug generation and uniqueness helpers."""

from __future__ import annotations

from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlmodel import col, select

from app.core.exceptions import ValidationError
from app.utils.slugify import slugify
from models.product import Product


async def sku_exists(session: Any, sku: str, exclude_id: int | None = None) -> bool:
    """Return True if another product already uses this SKU."""
    if not sku:
        return False
    stmt = select(Product.id).where(col(Product.sku) == sku)
    if exclude_id is not None:
        stmt = stmt.where(col(Product.id) != exclude_id)
    result = await session.execute(stmt)
    return result.scalar_one_or_none() is not None


async def slug_exists(session: Any, slug: str, exclude_id: int | None = None) -> bool:
    """Return True if another product already uses this slug."""
    stmt = select(Product.id).where(col(Product.slug) == slug)
    if exclude_id is not None:
        stmt = stmt.where(col(Product.id) != exclude_id)
    result = await session.execute(stmt)
    return result.scalar_one_or_none() is not None


async def product_has_order_items(session: Any, product_id: int) -> bool:
    """Return True if any order line item references this product."""
    from models.order_item import OrderItem

    result = await session.execute(
        select(OrderItem.id).where(col(OrderItem.product_id) == product_id).limit(1)
    )
    return result.scalar_one_or_none() is not None


def _product_slug_source(product: Product) -> str:
    """Build slug source from name plus optional Product type option."""
    qualifier = (product.options or {}).get("Product type")
    if qualifier and str(qualifier).strip():
        return f"{product.name} {qualifier.strip()}"
    return product.name


async def generate_unique_product_slug(
    session: Any,
    name: str,
    *,
    exclude_id: int | None = None,
    preferred: str | None = None,
) -> str:
    """Generate a unique URL slug from a product name or preferred value."""
    base = slugify(preferred or name) or "product"
    candidate = base
    suffix = 2
    while await slug_exists(session, candidate, exclude_id):
        candidate = f"{base}-{suffix}"
        suffix += 1
    return candidate


async def ensure_product_slug(
    session: Any,
    product: Product,
    *,
    preferred: str | None = None,
) -> str:
    """Assign a slug to the product when missing; return the effective slug."""
    if product.slug and not preferred:
        return product.slug

    product.slug = await generate_unique_product_slug(
        session,
        _product_slug_source(product),
        exclude_id=product.id,
        preferred=preferred or product.slug,
    )
    return product.slug


def raise_friendly_product_integrity_error(exc: IntegrityError) -> None:
    """Map unique constraint failures to validation errors for product fields."""
    message = str(getattr(exc, "orig", exc)).lower()
    if "slug" in message:
        raise ValidationError(message="A product with this slug already exists") from exc
    if "sku" in message:
        raise ValidationError(message="A product with this SKU already exists") from exc
    raise exc
