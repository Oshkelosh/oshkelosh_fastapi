"""Price and variant helpers for supplier catalog normalization."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from schemas.supplier import (
    SupplierCatalogItem,
    SupplierCatalogProduct,
    SupplierCatalogVariant,
)


def decimal_price_to_cents(value: Any) -> int:
    if value is None or value == "":
        return 0
    try:
        return int(Decimal(str(value)) * 100)
    except (InvalidOperation, ValueError, TypeError):
        return 0


def int_price_to_cents(value: Any) -> int:
    if value is None:
        return 0
    try:
        return max(int(value), 0)
    except (TypeError, ValueError):
        return 0


def variant_dicts_from_row(row: dict[str, Any], *keys: str) -> list[dict[str, Any]]:
    """Return the first list-of-dicts variant array on a catalog row (ignore counts)."""
    for key in keys:
        value = row.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return []


def row_lacks_variant_list(row: dict[str, Any], *keys: str) -> bool:
    """True when no non-empty variant list is present on the row."""
    return not variant_dicts_from_row(row, *keys)


def variant_attributes_from_row(row: dict[str, Any], *keys: str) -> dict[str, str]:
    """Extract string attributes from common supplier variant field names.

    Printful sync should use ``printful_variant_attributes_from_row`` instead —
    Printful ``name`` is a display title, not a purchasable option axis.
    """
    attrs: dict[str, str] = {}
    mapping = {
        "size": "Size",
        "color": "Color",
        "variantName": "Variant",
        "name": "Option",
    }
    for key, label in mapping.items():
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            attrs[label] = value.strip()
    for key in keys:
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            attrs[key.title()] = value.strip()
    return attrs


def variant_title_from_attributes(
    base_name: str,
    attributes: dict[str, str],
    *,
    fallback: str = "",
) -> str:
    """Build variant display title from attribute values."""
    if attributes:
        ordered = [attributes[k] for k in sorted(attributes.keys())]
        return " / ".join(ordered)
    return fallback or base_name


def flat_catalog_item_to_product(item: SupplierCatalogItem) -> SupplierCatalogProduct:
    """Wrap a legacy flat catalog item as a single-variant product."""
    image_urls = list(item.image_urls) if item.image_urls else []
    if item.image_url and item.image_url not in image_urls:
        image_urls.insert(0, item.image_url)
    alts = list(item.image_alt_texts) if item.image_alt_texts else []
    variant = SupplierCatalogVariant(
        external_key=item.external_key,
        title=item.name,
        attributes={},
        price_cents=item.price_cents,
        sku=item.sku,
        inventory_quantity=item.inventory_quantity,
        supplier_product_id=item.supplier_product_id,
        supplier_variant_id=item.supplier_variant_id,
        image_urls=image_urls,
        image_alt_texts=alts,
        skip_reason=item.skip_reason,
    )
    options: dict[str, str] = {}
    if item.product_type:
        options["Product type"] = item.product_type
    return SupplierCatalogProduct(
        external_product_key=item.external_key,
        name=item.name,
        description=item.description,
        product_type=item.product_type,
        image_urls=[],
        image_alt_texts=[],
        variants=[variant],
        supplier_value=item.supplier_value,
        options=options,
    )


def ensure_catalog_products(
    items: list[SupplierCatalogItem | SupplierCatalogProduct],
) -> list[SupplierCatalogProduct]:
    """Normalize fetch_catalog_for_import output to grouped products."""
    products: list[SupplierCatalogProduct] = []
    for item in items:
        if isinstance(item, SupplierCatalogProduct):
            products.append(item)
        else:
            products.append(flat_catalog_item_to_product(item))
    return products
