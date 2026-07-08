"""Product creation defaults and immutable-field enforcement."""

from __future__ import annotations

from typing import Any

from sqlmodel import col, select

from app.db.connection import mark_instance_dirty
from app.services.product_slugs import ensure_product_slug
from app.services.suppliers import (
    is_supplier_tag,
    is_sync_marker_tag,
)
from app.storefront.seo import truncate_text
from app.utils.slugify import slugify
from models.category import Category
from models.product import Product

_DESCRIPTION_MAX = 160


def default_product_meta(product: Product, store_name: str) -> tuple[str, str | None]:
    """Return default meta_title and meta_description for a product."""
    qualifier = (product.options or {}).get("Product type")
    if qualifier and str(qualifier).strip():
        display = f"{product.name} – {qualifier.strip()}"
    else:
        display = product.name
    title = f"{display} | {store_name}"
    description = truncate_text(product.description, _DESCRIPTION_MAX)
    return title, description


async def apply_product_creation_defaults(
    session: Any,
    product: Product,
    *,
    store_name: str,
    preferred_slug: str | None = None,
) -> None:
    """Persist slug and meta fields when missing at product creation."""
    slug_preferred = preferred_slug.strip() if preferred_slug and preferred_slug.strip() else None
    await ensure_product_slug(session, product, preferred=slug_preferred)

    if not product.meta_title:
        meta_title, meta_description = default_product_meta(product, store_name)
        product.meta_title = meta_title
        if not product.meta_description:
            product.meta_description = meta_description
    elif not product.meta_description:
        _, meta_description = default_product_meta(product, store_name)
        product.meta_description = meta_description


async def _unique_category_slug(session: Any, base_slug: str) -> str:
    candidate = base_slug or "category"
    suffix = 2
    while True:
        result = await session.execute(select(Category.id).where(col(Category.slug) == candidate))
        if result.scalar_one_or_none() is None:
            return candidate
        candidate = f"{base_slug}-{suffix}"
        suffix += 1


async def assign_product_category_from_type(
    session: Any,
    product: Product,
    product_type: str | None,
) -> None:
    """Create a Category from supplier product type and link it to the product."""
    if not product_type or not str(product_type).strip():
        return
    name = str(product_type).strip()
    base_slug = slugify(name) or "category"
    result = await session.execute(select(Category).where(col(Category.slug) == base_slug))
    category = result.scalar_one_or_none()
    if category is None:
        slug = await _unique_category_slug(session, base_slug)
        category = Category(name=name, slug=slug)
        session.add(category)
        await session.flush()
        from app.services.category_defaults import apply_category_creation_defaults
        from app.services.site_settings import get_site_settings

        site_settings = await get_site_settings(session)
        store_name = site_settings.store_name or "Store"
        await apply_category_creation_defaults(session, category, store_name=store_name)
    product.category_id = category.id
    mark_instance_dirty(session, product)


def product_is_sync_imported(product: Product) -> bool:
    """Return True when the product was imported via supplier catalog sync."""
    return any(is_sync_marker_tag(tag) for tag in (product.tags or []))


def refresh_sync_marker_only(tags: list[Any] | None, external_key: str) -> list[Any]:
    """Update the sync marker without changing supplier assignment tags."""
    kept = [t for t in (tags or []) if not is_sync_marker_tag(t)]
    kept.append({"supplier_sync": True, "supplier_external_key": external_key})
    return kept


def _normalize_optional(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def enforce_immutable_product_fields(
    product: Product,
    variant: Any | None,
    *,
    sku: str | None,
    supplier_value: str,
    supplier_product_id: str,
    supplier_variant_id: str,
    category_id: int | None,
) -> str | None:
    """Return an error message if immutable fields were changed, else None."""
    from app.services.suppliers import supplier_form_values_from_variant

    stored_sku = _normalize_optional(product.sku)
    submitted_sku = _normalize_optional(sku)
    if stored_sku != submitted_sku:
        return "SKU cannot be changed after the product is created."

    if variant is not None:
        stored_supplier_value, stored_product_id, stored_variant_id = (
            supplier_form_values_from_variant(variant)
        )
        if stored_supplier_value != supplier_value.strip():
            return "Supplier cannot be changed after the product is created."
        if stored_product_id != supplier_product_id.strip():
            return "Supplier product ID cannot be changed after the product is created."
        if stored_variant_id != supplier_variant_id.strip():
            return "Supplier variant ID cannot be changed after the product is created."

    if product_is_sync_imported(product):
        if product.category_id != category_id:
            return "Category cannot be changed for catalog-synced products."

    return None


def validate_api_product_update(product: Product, update_data: dict[str, Any]) -> None:
    """Raise ValidationError when an API patch touches immutable product fields."""
    from app.core.exceptions import ValidationError

    if "sku" in update_data:
        stored_sku = _normalize_optional(product.sku)
        submitted_sku = _normalize_optional(update_data.get("sku"))
        if stored_sku != submitted_sku:
            raise ValidationError(message="SKU cannot be changed after the product is created.")

    if product_is_sync_imported(product) and "category_id" in update_data:
        if product.category_id != update_data.get("category_id"):
            raise ValidationError(
                message="Category cannot be changed for catalog-synced products."
            )
