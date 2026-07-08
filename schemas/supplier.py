"""Shared supplier catalog import and assignment types."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

POD_INVENTORY_PLACEHOLDER = 9999

SUPPLIER_TAG_KEYS = frozenset(
    {
        "supplier_addon_id",
        "manual_supplier_slug",
        "supplier_ref",
        "supplier_product_id",
        "supplier_variant_id",
    }
)


@dataclass(frozen=True)
class SupplierAssignment:
    """Normalized supplier linkage from a product tag."""

    addon_id: str
    supplier_product_id: str
    manual_slug: str | None = None
    variant_id: str | None = None

    @property
    def fulfillment_key(self) -> str:
        """Unique key for grouping line items by supplier destination."""
        from app.services.suppliers import supplier_fulfillment_key

        return supplier_fulfillment_key(self)


@dataclass(frozen=True)
class SupplierOption:
    """Selectable supplier for admin product forms."""

    value: str
    label: str
    addon_id: str
    manual_slug: str | None = None


@dataclass
class SupplierCatalogVariant:
    """Normalized sellable variant from a supplier catalog."""

    external_key: str
    title: str
    attributes: dict[str, str]
    price_cents: int
    sku: str | None
    inventory_quantity: int
    supplier_product_id: str
    supplier_variant_id: str
    image_urls: list[str] = field(default_factory=list)
    image_alt_texts: list[str] = field(default_factory=list)
    skip_reason: str | None = None


@dataclass
class SupplierCatalogProduct:
    """Normalized product (design) with child variants from a supplier catalog."""

    external_product_key: str
    name: str
    description: str | None
    product_type: str | None
    image_urls: list[str]
    image_alt_texts: list[str]
    variants: list[SupplierCatalogVariant]
    supplier_value: str
    options: dict[str, str] = field(default_factory=dict)


@dataclass
class SupplierCatalogItem:
    """Normalized sellable unit from a supplier catalog."""

    external_key: str
    name: str
    description: str | None
    price_cents: int
    sku: str | None
    image_url: str | None
    supplier_value: str
    supplier_product_id: str
    supplier_variant_id: str
    inventory_quantity: int
    skip_reason: str | None = None
    product_type: str | None = None
    image_urls: list[str] = field(default_factory=list)
    image_alt_texts: list[str] = field(default_factory=list)
