"""Supplier-aware shipping quote orchestration."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from app.services.addons import get_supplier_addon
from app.services.pricing.tax_rules import compute_site_shipping_cents
from app.services.pricing.protocols import ShippingQuote
from app.services.suppliers import (
    SupplierAssignment,
    supplier_assignment_from_variant,
    supplier_fulfillment_key,
)
from models.product import Product
from models.product_variant import ProductVariant
from models.site_settings import SiteSettings

logger = logging.getLogger(__name__)

_MERCHANT_GROUP_KEY = "__merchant__"


@dataclass
class _ShippingGroup:
    key: str
    assignment: SupplierAssignment | None
    items: list[dict[str, Any]]
    subtotal_cents: int


def group_cart_for_shipping(
    cart_items: list[Any],
    products: dict[int, Product],
    variants: dict[int, ProductVariant] | None = None,
) -> list[_ShippingGroup]:
    groups: dict[str, _ShippingGroup] = {}

    for item in cart_items:
        product = products.get(item.product_id)
        if product is None:
            continue
        variant = (variants or {}).get(getattr(item, "variant_id", None))
        quantity = getattr(item, "quantity", 1)
        unit_price = variant.price_cents if variant is not None else product.price_cents
        line_total = unit_price * quantity
        assignment = (
            supplier_assignment_from_variant(variant)
            if variant is not None
            else None
        )
        key = (
            supplier_fulfillment_key(assignment)
            if assignment is not None
            else _MERCHANT_GROUP_KEY
        )
        if key not in groups:
            groups[key] = _ShippingGroup(
                key=key,
                assignment=assignment,
                items=[],
                subtotal_cents=0,
            )
        group = groups[key]
        group.subtotal_cents += line_total
        group.items.append(
            {
                "product_id": product.id,
                "variant_id": variant.id if variant is not None else None,
                "supplier_product_id": assignment.supplier_product_id if assignment else None,
                "supplier_variant_id": assignment.variant_id if assignment else None,
                "quantity": quantity,
                "product_name": (
                    f"{product.name} — {variant.title}" if variant else product.name
                ),
                "unit_price_cents": unit_price,
                "total_price_cents": line_total,
            }
        )
    return list(groups.values())


async def quote_shipping_cents(
    groups: list[_ShippingGroup],
    site: SiteSettings,
    shipping_address: dict[str, Any] | None,
) -> tuple[int, list[dict[str, Any]]]:
    breakdown: list[dict[str, Any]] = []
    shipping_total = 0
    merchant_subtotal = 0

    for group in groups:
        quoted = False
        if group.assignment is not None and group.key != _MERCHANT_GROUP_KEY:
            addon = get_supplier_addon(group.assignment.addon_id)
            if addon is not None and addon.supports_shipping_quotes():
                try:
                    amount = await addon.quote_shipping(
                        group.items,
                        shipping_address or {},
                    )
                except Exception:
                    logger.exception(
                        "Supplier '%s' quote_shipping failed; using site settings",
                        group.assignment.addon_id,
                    )
                    amount = None
                if amount is not None:
                    shipping_total += max(0, int(amount))
                    breakdown.append(
                        {
                            "source": "supplier",
                            "addon_id": group.assignment.addon_id,
                            "fulfillment_key": group.key,
                            "cents": max(0, int(amount)),
                        }
                    )
                    quoted = True
        if not quoted:
            merchant_subtotal += group.subtotal_cents

    if merchant_subtotal > 0:
        site_amount = compute_site_shipping_cents(
            merchant_subtotal,
            site,
            shipping_address,
        )
        shipping_total += site_amount
        breakdown.append(
            {
                "source": "site_settings",
                "fulfillment_key": _MERCHANT_GROUP_KEY,
                "subtotal_cents": merchant_subtotal,
                "cents": site_amount,
            }
        )

    return shipping_total, breakdown


class SiteShippingQuoter:
    """Apply site settings and supplier shipping quotes."""

    def __init__(self, site: SiteSettings) -> None:
        self._site = site

    async def quote(
        self,
        cart_items: list[Any],
        products: dict[int, Product],
        shipping_address: dict[str, Any] | None,
        variants: dict[int, ProductVariant] | None = None,
    ) -> ShippingQuote:
        groups = group_cart_for_shipping(cart_items, products, variants)
        shipping_cents, breakdown = await quote_shipping_cents(
            groups,
            self._site,
            shipping_address,
        )
        return ShippingQuote(shipping_cents=shipping_cents, breakdown=breakdown)
