"""Product variant helpers: listing cache, resolution, supplier linkage."""

from __future__ import annotations

from typing import Any, Sequence

from sqlalchemy import select
from sqlmodel import col

from app.core.exceptions import NotFound, ValidationError
from models.product import Product
from models.product_variant import ProductVariant
from schemas.supplier import SupplierAssignment

__all__ = [
    "VARIANT_STATUS_ACTIVE",
    "VARIANT_STATUS_ARCHIVED",
    "build_variant_snapshot",
    "create_default_variant",
    "ensure_variant_purchasable",
    "get_active_variants",
    "get_variant_for_product",
    "get_variants_for_products",
    "list_variants_for_product",
    "refresh_product_listing_cache",
    "resolve_unique_variant_sku",
    "supplier_assignment_from_variant",
]


VARIANT_STATUS_ACTIVE = "active"
VARIANT_STATUS_ARCHIVED = "archived"


def get_active_variants(variants: Sequence[ProductVariant]) -> list[ProductVariant]:
    """Return active variants sorted by position then id."""
    active = [v for v in variants if v.status == VARIANT_STATUS_ACTIVE]
    return sorted(active, key=lambda v: (v.position, v.id or 0))


async def get_variants_for_products(
    session: Any,
    product_ids: Sequence[int],
) -> dict[int, list[ProductVariant]]:
    """Load variants for multiple products."""
    if not product_ids:
        return {}
    result = await session.execute(
        select(ProductVariant).where(col(ProductVariant.product_id).in_(list(product_ids)))
    )
    by_product: dict[int, list[ProductVariant]] = {pid: [] for pid in product_ids}
    for variant in result.scalars().all():
        by_product.setdefault(variant.product_id, []).append(variant)
    return by_product


async def list_variants_for_product(session: Any, product_id: int) -> list[ProductVariant]:
    """Return all variants for a product sorted by position then id."""
    result = await session.execute(
        select(ProductVariant)
        .where(col(ProductVariant.product_id) == product_id)
        .order_by(col(ProductVariant.position).asc(), col(ProductVariant.id).asc())
    )
    return list(result.scalars().all())


async def get_variant_for_product(
    session: Any,
    product_id: int,
    variant_id: int,
) -> ProductVariant:
    """Load a variant and ensure it belongs to the product."""
    variant = await session.get(ProductVariant, variant_id)
    if variant is None or variant.product_id != product_id:
        raise NotFound(message="Variant not found for this product")
    return variant


def ensure_variant_purchasable(product: Product, variant: ProductVariant, quantity: int = 1) -> None:
    """Raise if variant cannot be purchased."""
    if product.status != "published":
        raise ValidationError(message=f"Product '{product.name}' is not available for purchase")
    if variant.status != VARIANT_STATUS_ACTIVE:
        raise ValidationError(message=f"Variant '{variant.title}' is not available for purchase")
    if quantity > variant.inventory_quantity:
        raise ValidationError(
            message=f"Insufficient inventory for '{product.name}' — {variant.title}"
        )


def build_variant_snapshot(variant: ProductVariant) -> dict[str, Any]:
    """Snapshot variant display fields for order history."""
    return {
        "title": variant.title,
        "sku": variant.sku or "",
        "attributes": dict(variant.attributes or {}),
    }


def supplier_assignment_from_variant(variant: ProductVariant) -> SupplierAssignment | None:
    """Build supplier assignment from variant supplier fields."""
    addon_id = variant.supplier_addon_id
    if not addon_id:
        return None
    product_id = variant.supplier_product_id or ""
    if addon_id == "manual":
        manual_slug = (
            variant.supplier_variant_id
            or (variant.attributes or {}).get("manual_supplier_slug")
        )
        return SupplierAssignment(
            addon_id="manual",
            supplier_product_id=product_id,
            manual_slug=str(manual_slug) if manual_slug else None,
            variant_id=None,
        )
    if not product_id and not variant.supplier_variant_id:
        return None
    return SupplierAssignment(
        addon_id=str(addon_id),
        supplier_product_id=str(product_id),
        variant_id=str(variant.supplier_variant_id) if variant.supplier_variant_id else None,
    )


async def resolve_unique_variant_sku(
    session: Any,
    sku: str | None,
    exclude_id: int | None = None,
) -> str | None:
    """Return a unique variant SKU, suffixing when needed."""
    if not sku:
        return None
    base = sku.strip()
    if not base:
        return None
    candidate = base
    suffix = 2
    while True:
        stmt = select(ProductVariant).where(col(ProductVariant.sku) == candidate)
        if exclude_id is not None:
            stmt = stmt.where(col(ProductVariant.id) != exclude_id)
        existing = await session.execute(stmt)
        if existing.scalar_one_or_none() is None:
            return candidate
        candidate = f"{base}-{suffix}"
        suffix += 1
        if suffix > 100:
            return None


def refresh_product_listing_cache(product: Product, variants: Sequence[ProductVariant]) -> None:
    """Update denormalized listing fields from active variants."""
    active = get_active_variants(variants)
    if not active:
        product.has_variants = False
        product.price_cents = product.price_cents if product.price_cents is not None else 0
        product.inventory_quantity = 0
        return

    product.has_variants = len(active) > 1
    product.price_cents = min(v.price_cents for v in active)
    product.inventory_quantity = sum(v.inventory_quantity for v in active)
    default = active[0]
    product.sku = default.sku
    cap = default.compare_at_price_cents
    product.compare_at_price_cents = cap if cap is not None else None


async def create_default_variant(
    session: Any,
    product: Product,
    *,
    title: str | None = None,
    price_cents: int | None = None,
    inventory_quantity: int | None = None,
    sku: str | None = None,
    supplier_addon_id: str | None = None,
    supplier_product_id: str | None = None,
    supplier_variant_id: str | None = None,
) -> ProductVariant:
    """Create a single default variant for a manually created product."""
    variant = ProductVariant(
        product_id=product.id,
        title=title or product.name,
        position=0,
        price_cents=price_cents if price_cents is not None else product.price_cents,
        compare_at_price_cents=product.compare_at_price_cents,
        inventory_quantity=(
            inventory_quantity if inventory_quantity is not None else product.inventory_quantity
        ),
        sku=sku or product.sku,
        status=VARIANT_STATUS_ACTIVE,
        attributes={},
        supplier_addon_id=supplier_addon_id,
        supplier_product_id=supplier_product_id,
        supplier_variant_id=supplier_variant_id,
    )
    session.add(variant)
    await session.flush()
    refresh_product_listing_cache(product, [variant])
    return variant
