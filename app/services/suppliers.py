"""Supplier assignment helpers for fulfillment and admin.

Core orchestrates supplier linkage; per-provider tag rules live on ``SupplierAddon``
hooks. See app/addons/suppliers/README.md (Data model).
"""

from __future__ import annotations

from typing import Any

from app.addons import addon_registry
from app.addons.suppliers.base import SupplierAddon
from models.product import Product
from schemas.supplier import (
    SUPPLIER_TAG_KEYS,
    SupplierAssignment,
    SupplierOption,
)

__all__ = [
    "SUPPLIER_TAG_KEYS",
    "SupplierAssignment",
    "SupplierOption",
    "build_supplier_form_meta",
    "is_supplier_tag",
    "is_sync_marker_tag",
    "list_supplier_options",
    "non_supplier_tags",
    "parse_supplier_tag",
    "supplier_assignment_label",
    "supplier_assignment_from_product",
    "supplier_assignment_from_variant",
    "supplier_form_values",
    "supplier_form_values_from_variant",
    "variant_supplier_label",
    "supplier_fulfillment_key",
    "validate_supplier_form",
]


def _ensure_suppliers_registered() -> None:
    addon_registry.register_all()


def _resolve_supplier_addon(addon_id: str) -> SupplierAddon | None:
    _ensure_suppliers_registered()
    addon = addon_registry.get(addon_id)
    if isinstance(addon, SupplierAddon):
        return addon
    return None


def _addon_id_from_supplier_value(supplier_value: str) -> str:
    if supplier_value.startswith("manual:"):
        return "manual"
    return supplier_value


def parse_supplier_tag(tag: dict[str, Any]) -> SupplierAssignment | None:
    """Return a supplier assignment from a tag dict, or None if not a supplier tag."""
    if not isinstance(tag, dict):
        return None
    addon_id = tag.get("supplier_addon_id")
    if not addon_id:
        return None
    addon = _resolve_supplier_addon(str(addon_id))
    if addon is None:
        return None
    return addon.parse_assignment(tag)


def supplier_assignment_from_variant(variant: Any) -> SupplierAssignment | None:
    """Return supplier assignment from a product variant row."""
    from app.services.product_variants import supplier_assignment_from_variant as _from_variant

    return _from_variant(variant)


def supplier_assignment_from_product(product: Product) -> SupplierAssignment | None:
    """Return the first supplier assignment tag on a product."""
    for tag in product.tags or []:
        assignment = parse_supplier_tag(tag)
        if assignment is not None:
            return assignment
    return None


def supplier_fulfillment_key(assignment: SupplierAssignment) -> str:
    """Unique key for grouping line items by supplier destination."""
    addon = _resolve_supplier_addon(assignment.addon_id)
    if addon is not None:
        return addon.fulfillment_key(assignment)
    return assignment.addon_id


def is_supplier_tag(tag: Any) -> bool:
    """True if tag dict is a supplier linkage tag."""
    return isinstance(tag, dict) and bool(tag.get("supplier_addon_id"))


def is_sync_marker_tag(tag: Any) -> bool:
    """True if tag dict is a supplier catalog sync marker."""
    return isinstance(tag, dict) and bool(tag.get("supplier_sync"))


def validate_supplier_form(
    supplier_value: str,
    supplier_product_id: str = "",
    supplier_variant_id: str = "",
) -> str | None:
    """Return an error message if supplier fields are invalid, else None."""
    if not supplier_value:
        return None
    addon = _resolve_supplier_addon(_addon_id_from_supplier_value(supplier_value))
    if addon is None:
        return "Unknown supplier."
    return addon.validate_admin_form(supplier_value, supplier_product_id, supplier_variant_id)


def supplier_form_values_from_variant(variant: Any | None) -> tuple[str, str, str]:
    """Return supplier form tuple from a variant row."""
    if variant is None:
        return "", "", ""
    assignment = supplier_assignment_from_variant(variant)
    if assignment is None:
        return "", "", ""
    addon = _resolve_supplier_addon(assignment.addon_id)
    variant_id = assignment.variant_id or ""
    if addon is not None:
        return addon.assignment_dropdown_value(assignment), assignment.supplier_product_id, variant_id
    return assignment.addon_id, assignment.supplier_product_id, variant_id


def supplier_form_values(product: Product | None, variant: Any | None = None) -> tuple[str, str, str]:
    """Return (supplier_value, supplier_product_id, supplier_variant_id) for the form."""
    if variant is not None:
        return supplier_form_values_from_variant(variant)
    if product is None:
        return "", "", ""
    assignment = supplier_assignment_from_product(product)
    if assignment is None:
        return "", "", ""
    variant_id = assignment.variant_id or ""
    addon = _resolve_supplier_addon(assignment.addon_id)
    if addon is not None:
        return addon.assignment_dropdown_value(assignment), assignment.supplier_product_id, variant_id
    return assignment.addon_id, assignment.supplier_product_id, variant_id


def variant_supplier_label(variant: Any | None) -> str:
    """Human-readable supplier label for a variant."""
    if variant is None:
        return ""
    return supplier_assignment_label(supplier_assignment_from_variant(variant))


def non_supplier_tags(tags: list[Any] | None) -> list[Any]:
    """Return tags that are not supplier linkage entries."""
    return [t for t in (tags or []) if not is_supplier_tag(t)]


def build_supplier_form_meta() -> dict[str, dict[str, str | bool]]:
    """Return admin product-form metadata keyed by supplier dropdown value."""
    _ensure_suppliers_registered()
    meta: dict[str, dict[str, str | bool]] = {}
    for addon in addon_registry.iter_addons():
        if not isinstance(addon, SupplierAddon):
            continue
        meta[addon.admin_form_meta_key()] = addon.admin_form_hints()
    return meta


def supplier_assignment_label(assignment: SupplierAssignment | None) -> str:
    """Human-readable supplier name for admin lists."""
    if assignment is None:
        return ""
    addon = _resolve_supplier_addon(assignment.addon_id)
    if addon is not None:
        return addon.assignment_display_label(assignment)
    return assignment.addon_id


async def list_supplier_options(session: Any) -> list[SupplierOption]:
    """Return supplier choices for admin dropdowns."""
    _ensure_suppliers_registered()
    options: list[SupplierOption] = []

    for addon in addon_registry.iter_addons():
        if not isinstance(addon, SupplierAddon):
            continue
        if addon.lists_options_when_disabled() or addon.is_enabled:
            options.extend(await addon.list_admin_options(session))

    return options
